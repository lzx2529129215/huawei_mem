// SPDX-License-Identifier: GPL-2.0
/*
 * Tier-2 Watermark for Proactive Demotion and Memory Tiering
 *
 * Implements a secondary watermark system on top of the existing
 * min/low/high/promo zone watermarks. Provides alloc/demote watermarks
 * at the node level, statistics, EWMA-based prediction, and a
 * sysfs state interface for userspace aging/prediction tools.
 *
 * Designed to work with the existing memory-tiers infrastructure
 * (WMARK_PROMO, node_is_toptier, next_demotion_node, demote_folio_list).
 */

#include <linux/kernel.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/swap.h>
#include <linux/vmstat.h>
#include <linux/atomic.h>
#include <linux/seq_file.h>
#include <linux/sysfs.h>
#include <linux/kobject.h>
#include <linux/nodemask.h>
#include <linux/memory-tiers.h>
#include <linux/tier2_watermark.h>
#include <linux/sched/sysctl.h>
#include <linux/ktime.h>
#include <linux/math64.h>

#include <linux/memcontrol.h>
#include <linux/page_counter.h>
#include "internal.h"

/* Global configuration - accessible via /proc/sys/vm/ */
int sysctl_tier2_wmark_enabled __read_mostly = 0;
int sysctl_tier2_alloc_scale_factor __read_mostly = 100;   /* 1.00% */
int sysctl_tier2_demote_scale_factor __read_mostly = 300;  /* 3.00% */

/* Global vmstat-like tier2 counters (sum across all memcgs) */
atomic64_t tier2_global_below_alloc = ATOMIC64_INIT(0);
atomic64_t tier2_global_below_demote = ATOMIC64_INIT(0);
atomic64_t tier2_global_reclaim_actual = ATOMIC64_INIT(0);
atomic64_t tier2_global_reclaim_pages = ATOMIC64_INIT(0);
EXPORT_SYMBOL_GPL(tier2_global_below_alloc);
EXPORT_SYMBOL_GPL(tier2_global_below_demote);
EXPORT_SYMBOL_GPL(tier2_global_reclaim_actual);
EXPORT_SYMBOL_GPL(tier2_global_reclaim_pages);

/* Per-node tier2 watermark state */
static struct tier2_wmark_node *tier2_wmark_nodes __read_mostly;

/* EWMA decay factor: alpha = 1/16 -> ~16-sample window */
#define TIER2_EWMA_SHIFT 4

/* sysfs kobject */
static struct kobject *tier2_wmark_kobj;



bool tier2_wmark_enabled(void)
{
	return !!READ_ONCE(sysctl_tier2_wmark_enabled);
}
EXPORT_SYMBOL_GPL(tier2_wmark_enabled);

/*
 * Determine the role of a node: top, slow, or unknown.
 * Uses existing memory-tiers infrastructure.
 */
static __maybe_unused const char *tier2_wmark_node_role(int nid)
{
	if (!node_state(nid, N_MEMORY))
		return "unknown";
	if (node_is_toptier(nid))
		return "top";
	if (node_state(nid, N_CPU))
		return "top";
	return "slow";
}

/*
 * Return the first managed zone for a pgdat, for watermark comparison.
 */
static struct zone *first_managed_zone_pgdat(struct pglist_data *pgdat)
{
	struct zone *zone;
	int z;

	for ((z) = 0, (zone) = (pgdat)->node_zones; (z) <= (ZONE_MOVABLE); (z)++, (zone)++) if (managed_zone(zone))
		return zone;
	return NULL;
}

/*
 * Sum managed pages across managed zones in a node.
 */
static unsigned long tier2_managed_pages_pgdat(struct pglist_data *pgdat)
{
	unsigned long managed = 0;
	struct zone *zone;
	int z;

	for ((z) = 0, (zone) = (pgdat)->node_zones; (z) <= (ZONE_MOVABLE); (z)++, (zone)++) if (managed_zone(zone))
		managed += zone_managed_pages(zone);

	return managed;
}

/*
 * Calculate the alloc watermark for a pgdat (in pages).
 */
unsigned long tier2_wmark_alloc_pages_pgdat(struct pglist_data *pgdat)
{
	unsigned long managed = tier2_managed_pages_pgdat(pgdat);
	struct zone *zone;

	if (!managed)
		return 0;

	zone = first_managed_zone_pgdat(pgdat);
	if (!zone)
		return 0;

	return max(high_wmark_pages(zone),
		   managed * READ_ONCE(sysctl_tier2_alloc_scale_factor) / 10000);
}
EXPORT_SYMBOL_GPL(tier2_wmark_alloc_pages_pgdat);

/*
 * Calculate the demote watermark for a pgdat (in pages).
 * Must be >= alloc watermark.
 */
unsigned long tier2_wmark_demote_pages_pgdat(struct pglist_data *pgdat)
{
	unsigned long managed = tier2_managed_pages_pgdat(pgdat);
	unsigned long alloc_wmark = tier2_wmark_alloc_pages_pgdat(pgdat);

	if (!managed)
		return 0;

	return max(alloc_wmark,
		   managed * READ_ONCE(sysctl_tier2_demote_scale_factor) / 10000);
}
EXPORT_SYMBOL_GPL(tier2_wmark_demote_pages_pgdat);

/*
 * Get aggregate free pages for a node.
 */
static unsigned long tier2_wmark_node_free_pages(struct pglist_data *pgdat)
{
	unsigned long free_pages = 0;
	struct zone *zone;
	int z;

	for ((z) = 0, (zone) = (pgdat)->node_zones; (z) <= (ZONE_MOVABLE); (z)++, (zone)++) if (managed_zone(zone))
		free_pages += zone_page_state(zone, NR_FREE_PAGES);

	return free_pages;
}

/*
 * Check if node free pages are below alloc watermark.
 */
bool tier2_wmark_below_alloc(struct pglist_data *pgdat)
{
	unsigned long free_pages, alloc_wmark;

	if (!tier2_wmark_enabled())
		return false;

	free_pages = tier2_wmark_node_free_pages(pgdat);
	alloc_wmark = tier2_wmark_alloc_pages_pgdat(pgdat);

	return free_pages < alloc_wmark;
}
EXPORT_SYMBOL_GPL(tier2_wmark_below_alloc);

/*
 * Check if node free pages are below demote watermark.
 */
bool tier2_wmark_below_demote(struct pglist_data *pgdat)
{
	unsigned long free_pages, demote_wmark;

	if (!tier2_wmark_enabled())
		return false;

	free_pages = tier2_wmark_node_free_pages(pgdat);
	demote_wmark = tier2_wmark_demote_pages_pgdat(pgdat);

	return free_pages < demote_wmark;
}
EXPORT_SYMBOL_GPL(tier2_wmark_below_demote);

/*
 * Record that free pages dropped below some watermark.
 */
void tier2_wmark_record_below(struct pglist_data *pgdat)
{
	int nid = pgdat->node_id;

	if (!tier2_wmark_enabled() || !tier2_wmark_nodes)
		return;

	if (tier2_wmark_below_alloc(pgdat))
		atomic64_inc(&tier2_wmark_nodes[nid].stats.below_alloc);
	if (tier2_wmark_below_demote(pgdat))
		atomic64_inc(&tier2_wmark_nodes[nid].stats.below_demote);
}
EXPORT_SYMBOL_GPL(tier2_wmark_record_below);

/*
 * Record a reclaim wakeup due to tier2 watermark.
 */
void tier2_wmark_record_reclaim_wakeup(struct pglist_data *pgdat)
{
	int nid = pgdat->node_id;

	if (!tier2_wmark_enabled() || !tier2_wmark_nodes)
		return;

	atomic64_inc(&tier2_wmark_nodes[nid].stats.reclaim_wakeup);
}
EXPORT_SYMBOL_GPL(tier2_wmark_record_reclaim_wakeup);

/*
 * Record a demotion attempt.
 */
void tier2_wmark_record_demote_attempt(struct pglist_data *pgdat,
				       unsigned long nr_pages)
{
	int nid = pgdat->node_id;

	if (!tier2_wmark_enabled() || !tier2_wmark_nodes)
		return;

	atomic64_inc(&tier2_wmark_nodes[nid].stats.demote_attempt);
}
EXPORT_SYMBOL_GPL(tier2_wmark_record_demote_attempt);

/*
 * Record demotion result (success/fail counts).
 */
void tier2_wmark_record_demote_result(struct pglist_data *pgdat,
				      unsigned long success,
				      unsigned long fail)
{
	int nid = pgdat->node_id;

	if (!tier2_wmark_enabled() || !tier2_wmark_nodes)
		return;

	if (success)
		atomic64_add(success, &tier2_wmark_nodes[nid].stats.demote_success);
	if (fail)
		atomic64_add(fail, &tier2_wmark_nodes[nid].stats.demote_fail);
}
EXPORT_SYMBOL_GPL(tier2_wmark_record_demote_result);

/*
 * Update EWMA for a node. Uses exponential weighted moving average
 * with alpha = 1/16, giving a ~16-read smoothing window.
 * Returns the new EWMA value.
 */
void tier2_wmark_update_ewma(struct pglist_data *pgdat)
{
	int nid = pgdat->node_id;
	unsigned long free_pages, prev_ewma;

	if (!tier2_wmark_enabled() || !tier2_wmark_nodes)
		return;

	free_pages = tier2_wmark_node_free_pages(pgdat);
	prev_ewma = tier2_wmark_nodes[nid].ewma.ewma_free_pages;

	if (unlikely(!prev_ewma)) {
		tier2_wmark_nodes[nid].ewma.ewma_free_pages = free_pages;
	} else {
		/* EWMA = prev * (1 - 1/16) + sample * (1/16) */
		tier2_wmark_nodes[nid].ewma.ewma_free_pages =
			((prev_ewma << TIER2_EWMA_SHIFT) - prev_ewma +
			 free_pages) >> TIER2_EWMA_SHIFT;
	}

	tier2_wmark_nodes[nid].ewma.last_free_pages = free_pages;
	tier2_wmark_nodes[nid].ewma.last_update_jiffies = jiffies;
}
EXPORT_SYMBOL_GPL(tier2_wmark_update_ewma);

/*
 * sysfs state file: /sys/kernel/mm/tier2_watermark/state
 */
int tier2_wmark_state_show(struct seq_file *m, void *v)
{
	int nid;
	unsigned long now_jiffies __maybe_unused = jiffies;
	int enabled = READ_ONCE(sysctl_tier2_wmark_enabled);

	seq_printf(m, "version=1\n");
	seq_printf(m, "timestamp_ns=%llu\n", ktime_get_ns());
	seq_printf(m, "enabled=%d\n", enabled);

	for_each_online_node(nid) {
		struct pglist_data *pgdat = NODE_DATA(nid);
		struct zone *zone;
		int z;
		long predicted_alloc_sec __maybe_unused = -1;
		long predicted_demote_sec __maybe_unused = -1;

		if (!pgdat)
			continue;

		if (enabled && tier2_wmark_nodes)
			tier2_wmark_update_ewma(pgdat);

		for ((z) = 0, (zone) = (pgdat)->node_zones; (z) <= (ZONE_MOVABLE); (z)++, (zone)++) if (managed_zone(zone)) {
			unsigned long free_pages = zone_page_state(zone, NR_FREE_PAGES);
			unsigned long alloc_wmark =
				enabled ? tier2_wmark_alloc_pages_pgdat(pgdat) : 0;
			unsigned long demote_wmark =
				enabled ? tier2_wmark_demote_pages_pgdat(pgdat) : 0;
			unsigned long ewma_free = 0;

			if (enabled && tier2_wmark_nodes)
				ewma_free = tier2_wmark_nodes[nid].ewma.ewma_free_pages;

			/* Simple linear prediction based on EWMA-vs-current gap */
			if (enabled && ewma_free > 0 && tier2_wmark_nodes &&
			    tier2_wmark_nodes[nid].ewma.last_free_pages > 0) {
				unsigned long elapsed_jiffies =
					now_jiffies -
					tier2_wmark_nodes[nid].ewma.last_update_jiffies;
				unsigned long elapsed_sec =
					jiffies_to_msecs(elapsed_jiffies) / 1000;
				long delta = (long)free_pages -
					(long)tier2_wmark_nodes[nid].ewma.last_free_pages;

				if (free_pages < alloc_wmark) {
					predicted_alloc_sec = 0;
				} else if (delta < 0 && elapsed_sec > 0) {
					long rate = -delta / (long)max(elapsed_sec, 1UL);
					if (rate > 0)
						predicted_alloc_sec =
							(long)((free_pages - alloc_wmark) / rate);
				}

				if (free_pages < demote_wmark) {
					predicted_demote_sec = 0;
				} else if (delta < 0 && elapsed_sec > 0) {
					long rate = -delta / (long)max(elapsed_sec, 1UL);
					if (rate > 0)
						predicted_demote_sec =
							(long)((free_pages - demote_wmark) / rate);
				}
			}

			seq_printf(m,
				"node=%d\n"
				"zone=%s\n"
				"role=%s\n"
				"managed_pages=%lu\n"
				"free_pages=%lu\n"
				"min=%lu\n"
				"low=%lu\n"
				"high=%lu\n"
				"tier2_alloc_wmark=%lu\n"
				"tier2_demote_wmark=%lu\n"
				"below_alloc=%d\n"
				"below_demote=%d\n"
				"active_anon=%lu\n"
				"inactive_anon=%lu\n"
				"active_file=%lu\n"
				"inactive_file=%lu\n"
				"workingset_refault_anon=%ld\n"
				"workingset_refault_file=%ld\n"
				"pgdemote_success=%ld\n"
				"pgdemote_fail=%ld\n"
				"numa_pages_migrated=%ld\n"
				"ewma_free_pages=%lu\n"
				"predicted_seconds_to_alloc_wmark=%ld\n"
				"predicted_seconds_to_demote_wmark=%ld\n",
				nid,
				zone->name,
				tier2_wmark_node_role(nid),
				zone_managed_pages(zone),
				free_pages,
				min_wmark_pages(zone),
				low_wmark_pages(zone),
				high_wmark_pages(zone),
				alloc_wmark,
				demote_wmark,
				free_pages < alloc_wmark ? 1 : 0,
				free_pages < demote_wmark ? 1 : 0,
				zone_page_state(zone, NR_ACTIVE_ANON),
				zone_page_state(zone, NR_INACTIVE_ANON),
				zone_page_state(zone, NR_ACTIVE_FILE),
				zone_page_state(zone, NR_INACTIVE_FILE),
				(long)-1L /* vm_event, hard to get globally */,
				(long)-1L /* vm_event, hard to get globally */,
				(tier2_wmark_nodes ?
				 (long)atomic64_read(&tier2_wmark_nodes[nid].stats.demote_success) : -1L),
				(tier2_wmark_nodes ?
				 (long)atomic64_read(&tier2_wmark_nodes[nid].stats.demote_fail) : -1L),
				(long)-1L /* use NUMA_PAGE_MIGRATE vm_event instead */,
				ewma_free > 0 ? ewma_free : (unsigned long)-1,
				predicted_alloc_sec,
				predicted_demote_sec);
		}
	}

	return 0;
}
EXPORT_SYMBOL_GPL(tier2_wmark_state_show);

/* sysfs state file open/release */
static int tier2_wmark_state_open(struct inode *inode, struct file *file)
{
	return single_open(file, tier2_wmark_state_show, NULL);
}

static const struct file_operations tier2_wmark_state_fops = {
	.open		= tier2_wmark_state_open,
	.read		= seq_read,
	.llseek		= seq_lseek,
	.release	= single_release,
	.owner		= THIS_MODULE,
};

/* sysfs stats file */
static int tier2_wmark_stats_show(struct seq_file *m, void *v)
{
	int nid;

	seq_printf(m, "enabled=%d\n", READ_ONCE(sysctl_tier2_wmark_enabled));
	seq_printf(m, "alloc_scale_factor=%d\n",
		   READ_ONCE(sysctl_tier2_alloc_scale_factor));
	seq_printf(m, "demote_scale_factor=%d\n",
		   READ_ONCE(sysctl_tier2_demote_scale_factor));

	for_each_online_node(nid) {
		if (!tier2_wmark_nodes)
			break;

		seq_printf(m,
			"node=%d\n"
			"below_alloc=%ld\n"
			"below_demote=%ld\n"
			"reclaim_wakeup=%ld\n"
			"reclaim_target_adj=%ld\n"
			"demote_attempt=%ld\n"
			"demote_success=%ld\n"
			"demote_fail=%ld\n"
			"promotion_hint=%ld\n"
			"promotion_success=%ld\n"
			"pingpong_suspect=%ld\n",
			nid,
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.below_alloc),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.below_demote),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.reclaim_wakeup),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.reclaim_target_adj),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.demote_attempt),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.demote_success),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.demote_fail),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.promotion_hint),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.promotion_success),
			(long)atomic64_read(&tier2_wmark_nodes[nid].stats.pingpong_suspect));
	}

	return 0;
}

static int tier2_wmark_stats_open(struct inode *inode, struct file *file)
{
	return single_open(file, tier2_wmark_stats_show, NULL);
}

static const struct file_operations tier2_wmark_stats_fops = {
	.open		= tier2_wmark_stats_open,
	.read		= seq_read,
	.llseek		= seq_lseek,
	.release	= single_release,
	.owner		= THIS_MODULE,
};

/*
 * Create a sysfs file with custom file_operations.
 * Since we use seq_file-based fops, we create files as
 * "kernel objects" attributes manually.
 */
#ifdef CONFIG_DEBUG_FS
#include <linux/debugfs.h>
static struct dentry *tier2_wmark_debugfs_dir;

static int __init tier2_wmark_debugfs_init(void)
{
	tier2_wmark_debugfs_dir = debugfs_create_dir("tier2_watermark", NULL);
	if (!IS_ERR(tier2_wmark_debugfs_dir)) {
		debugfs_create_file("state", 0444, tier2_wmark_debugfs_dir,
				    NULL, &tier2_wmark_state_fops);
		debugfs_create_file("stats", 0444, tier2_wmark_debugfs_dir,
				    NULL, &tier2_wmark_stats_fops);
	}
	return 0;
}
#else
static inline int tier2_wmark_debugfs_init(void) { return 0; }
#endif

/*
 * Initialize per-node state.
 */
/* Forward declaration */

static int __init tier2_wmark_init(void)
{
	int nid;

	tier2_wmark_nodes = kcalloc(nr_node_ids, sizeof(*tier2_wmark_nodes),
				    GFP_KERNEL);
	if (!tier2_wmark_nodes) {
		pr_err("tier2_watermark: failed to allocate per-node state\n");
		return -ENOMEM;
	}

	/* Create /sys/kernel/mm/tier2_watermark/ for potential future use */
	tier2_wmark_kobj = kobject_create_and_add("tier2_watermark", mm_kobj);
	if (!tier2_wmark_kobj) {
		pr_warn("tier2_watermark: failed to create sysfs dir (non-fatal)\n");
	}

	/* Initialize EWMA */
	for_each_online_node(nid) {
		struct pglist_data *pgdat = NODE_DATA(nid);
		if (pgdat && tier2_wmark_nodes)
			tier2_wmark_nodes[nid].ewma.ewma_free_pages =
				tier2_wmark_node_free_pages(pgdat);
	}

	tier2_wmark_debugfs_init();

	/* Register per-memcg tier2 cgroup v1 files */

	pr_info("tier2_watermark: initialized (enabled=%d, alloc_scale=%d.%02d%%, demote_scale=%d.%02d%%)\n",
		READ_ONCE(sysctl_tier2_wmark_enabled),
		READ_ONCE(sysctl_tier2_alloc_scale_factor) / 100,
		READ_ONCE(sysctl_tier2_alloc_scale_factor) % 100,
		READ_ONCE(sysctl_tier2_demote_scale_factor) / 100,
		READ_ONCE(sysctl_tier2_demote_scale_factor) % 100);

	return 0;
}

module_init(tier2_wmark_init);


/* ================================================================
 * Per-memcg watermark calculation helpers
 * ================================================================ */

/*
 * Get the memory limit for a memcg in bytes.
 * Returns PAGE_COUNTER_MAX if unlimited.
 */
static unsigned long tier2_memcg_limit_bytes(struct mem_cgroup *memcg)
{
	unsigned long limit;

	if (!memcg)
		return PAGE_COUNTER_MAX;

	limit = READ_ONCE(memcg->memory.max);
	if (limit == PAGE_COUNTER_MAX)
		return PAGE_COUNTER_MAX;
	return limit * PAGE_SIZE;
}

/*
 * Get current memory usage for a memcg in bytes.
 */
static unsigned long tier2_memcg_usage_bytes(struct mem_cgroup *memcg)
{
	if (!memcg)
		return 0;

	return page_counter_read(&memcg->memory) * PAGE_SIZE;
}

/*
 * Compute per-memcg alloc watermark in bytes.
 *
 * alloc_wmark = max(PAGE_SIZE, limit * alloc_scale / 10000)
 *
 * If the memcg has no per-memcg tier2 enabled, falls back to global
 * settings (sysctl_tier2_alloc_scale_factor).
 */
static unsigned long tier2_memcg_alloc_wmark_bytes(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;
	unsigned long limit;
	int scale;

	if (!memcg || !memcg->tier2_wmark)
		return 0;

	tm = memcg->tier2_wmark;
	limit = tier2_memcg_limit_bytes(memcg);

	/* Unlimited limit = per-memcg tier2 disabled */
	if (limit == PAGE_COUNTER_MAX || limit == 0)
		return 0;

	scale = tm->enabled ? tm->alloc_scale : READ_ONCE(sysctl_tier2_alloc_scale_factor);
	if (scale <= 0)
		return 0;

	return max(limit * (unsigned long)scale / 10000UL, (unsigned long)PAGE_SIZE);
}

/*
 * Compute per-memcg demote watermark in bytes.
 *
 * demote_wmark = max(alloc_wmark, limit * demote_scale / 10000)
 */
static unsigned long tier2_memcg_demote_wmark_bytes(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;
	unsigned long limit, alloc_wmark;
	int scale;

	if (!memcg || !memcg->tier2_wmark)
		return 0;

	tm = memcg->tier2_wmark;
	limit = tier2_memcg_limit_bytes(memcg);

	if (limit == PAGE_COUNTER_MAX || limit == 0)
		return 0;

	alloc_wmark = tier2_memcg_alloc_wmark_bytes(memcg);
	scale = tm->enabled ? tm->demote_scale : READ_ONCE(sysctl_tier2_demote_scale_factor);
	if (scale <= 0)
		return alloc_wmark;

	return max(alloc_wmark, limit * (unsigned long)scale / 10000UL);
}

/*
 * Compute per-memcg headroom = limit - current_usage
 */
static unsigned long tier2_memcg_headroom_bytes(struct mem_cgroup *memcg)
{
	unsigned long limit, usage;

	if (!memcg)
		return 0;

	limit = tier2_memcg_limit_bytes(memcg);
	if (limit == PAGE_COUNTER_MAX)
		return ULONG_MAX;  /* unlimited => infinite headroom */

	usage = tier2_memcg_usage_bytes(memcg);
	if (usage >= limit)
		return 0;

	return limit - usage;
}

/* ================================================================
 * Per-memcg lifecycle
 * ================================================================ */

/*
 * Allocate and initialize per-memcg tier2 state.
 * Called from mem_cgroup_css_alloc().
 */
static void tier2_wmark_reclaim_work_fn(struct work_struct *work);

int tier2_wmark_memcg_alloc(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;

	if (!memcg)
		return -EINVAL;

	/* Don't allocate for root memcg (use global watermarks) */
	if (memcg == root_mem_cgroup)
		return 0;

	tm = kzalloc(sizeof(*tm), GFP_KERNEL);
	if (!tm)
		return -ENOMEM;

	/* Default: inherit global settings, but per-memcg is disabled */
	tm->enabled = 0;
	tm->alloc_scale = READ_ONCE(sysctl_tier2_alloc_scale_factor);
	tm->demote_scale = READ_ONCE(sysctl_tier2_demote_scale_factor);
	atomic64_set(&tm->below_alloc, 0);
	atomic64_set(&tm->below_demote, 0);
	atomic64_set(&tm->reclaim_triggered, 0);
	atomic64_set(&tm->reclaim_actual, 0);
	atomic64_set(&tm->reclaim_pages, 0);
	atomic64_set(&tm->pressure_count, 0);

	/* Back-pointer for workqueue access */
	tm->memcg = memcg;

	/* Initialize async reclaim work */
	INIT_WORK(&tm->reclaim_work, tier2_wmark_reclaim_work_fn);

	memcg->tier2_wmark = tm;
	return 0;
}

/*
 * Free per-memcg tier2 state.
 * Called from mem_cgroup_css_free().
 */
void tier2_wmark_memcg_free(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark)
		return;

	tm = memcg->tier2_wmark;

	/* Cancel pending reclaim work and wait for completion */
	cancel_work_sync(&tm->reclaim_work);

	kfree(tm);
	memcg->tier2_wmark = NULL;
}

/*
 * Update per-memcg computed watermarks.
 * Called when limit or scale factors change.
 */
void tier2_wmark_memcg_update(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark)
		return;

	tm = memcg->tier2_wmark;
	tm->limit_bytes = tier2_memcg_limit_bytes(memcg);
	tm->alloc_wmark_bytes = tier2_memcg_alloc_wmark_bytes(memcg);
	tm->demote_wmark_bytes = tier2_memcg_demote_wmark_bytes(memcg);
}

/*
 * Check per-memcg tier2 watermark status.
 * Called from try_charge path after a successful charge.
 *
 * Returns true if headroom is below demote watermark
 * (signals that proactive reclaim may be beneficial).
 */
bool tier2_wmark_memcg_check(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;
	unsigned long headroom, alloc_wmark, demote_wmark;
	bool below_alloc, below_demote;

	if (!memcg || !memcg->tier2_wmark)
		return false;

	tm = memcg->tier2_wmark;

	/* Skip if per-memcg tier2 is not enabled */
	if (!tm->enabled)
		return false;

	/* Skip root memcg */
	if (memcg == root_mem_cgroup)
		return false;

	/* Update watermarks (limit might have changed) */
	tm->limit_bytes = tier2_memcg_limit_bytes(memcg);
	if (tm->limit_bytes == PAGE_COUNTER_MAX || tm->limit_bytes == 0) {
		/* Unlimited cgroup: per-memcg tier2 is meaningless */
		return false;
	}

	tm->alloc_wmark_bytes = tier2_memcg_alloc_wmark_bytes(memcg);
	tm->demote_wmark_bytes = tier2_memcg_demote_wmark_bytes(memcg);

	if (tm->alloc_wmark_bytes == 0)
		return false;

	headroom = tier2_memcg_headroom_bytes(memcg);
	alloc_wmark = tm->alloc_wmark_bytes;
	demote_wmark = tm->demote_wmark_bytes;

	below_alloc = (headroom < alloc_wmark);
	below_demote = (headroom < demote_wmark);

	if (below_alloc)
		atomic64_inc(&tm->below_alloc);
	if (below_demote) {
		atomic64_inc(&tm->below_demote);
		atomic64_inc(&tm->reclaim_triggered);
	}

	return below_demote;
}

/*
 * Async reclaim work handler.
 * Called from workqueue when per-memcg tier2 detects memory pressure.
 * This runs asynchronously to avoid blocking the charge path.
 */
static void tier2_wmark_reclaim_work_fn(struct work_struct *work)
{
	struct tier2_wmark_memcg *tm =
		container_of(work, struct tier2_wmark_memcg, reclaim_work);
	struct mem_cgroup *memcg = tm->memcg;
	unsigned long headroom, demote_wmark, nr_to_reclaim;
	unsigned long usage_bytes;

	if (!memcg || !tm->enabled)
		return;

	/* Refresh watermarks */
	tm->limit_bytes = READ_ONCE(memcg->memory.max);
	if (tm->limit_bytes == PAGE_COUNTER_MAX || tm->limit_bytes == 0)
		return;
	tm->limit_bytes *= PAGE_SIZE;

	tm->alloc_wmark_bytes = max((unsigned long)PAGE_SIZE,
		tm->limit_bytes * (unsigned long)tm->alloc_scale / 10000UL);
	tm->demote_wmark_bytes = max(tm->alloc_wmark_bytes,
		tm->limit_bytes * (unsigned long)tm->demote_scale / 10000UL);

	usage_bytes = page_counter_read(&memcg->memory) * PAGE_SIZE;
	headroom = (usage_bytes < tm->limit_bytes) ?
		(tm->limit_bytes - usage_bytes) : 0;
	demote_wmark = tm->demote_wmark_bytes;

	/* Re-check: still below demote watermark? */
	if (headroom >= demote_wmark || demote_wmark == 0)
		return;

	/* Calculate reclaim target */
	nr_to_reclaim = (demote_wmark - headroom) / PAGE_SIZE;
	if (nr_to_reclaim < SWAP_CLUSTER_MAX)
		nr_to_reclaim = SWAP_CLUSTER_MAX;

	/*
	 * Perform proactive reclaim with MGLRU awareness.
	 * When MGLRU is enabled, the reclaim path (lru_gen_shrink_lruvec)
	 * automatically prioritizes cold (older generation) pages.
	 * We pass MEMCG_RECLAIM_PROACTIVE to mark this as proactive.
	 */
	try_to_free_mem_cgroup_pages(memcg, nr_to_reclaim,
				     GFP_KERNEL,
				     MEMCG_RECLAIM_MAY_SWAP | MEMCG_RECLAIM_PROACTIVE,
				     NULL);

	/* Update actual reclaim statistics */
	atomic64_inc(&tm->reclaim_actual);
	atomic64_add(nr_to_reclaim, &tm->reclaim_pages);
	atomic64_inc(&tm->pressure_count);

	/* Update global counters */
	atomic64_inc(&tier2_global_reclaim_actual);
	atomic64_add(nr_to_reclaim, &tier2_global_reclaim_pages);
}

/*
 * Check per-memcg tier2 watermark status AND schedule async reclaim
 * if headroom is below demote watermark.
 *
 * Called from try_charge_memcg() after a successful charge.
 * Uses workqueue for async reclaim to avoid blocking the charge path.
 * Rate limiting ensures we don't flood the workqueue.
 *
 * Returns true if reclaim work was scheduled.
 */
bool tier2_wmark_memcg_check_and_reclaim(struct mem_cgroup *memcg)
{
	struct tier2_wmark_memcg *tm;
	unsigned long headroom, demote_wmark;
	unsigned long triggered;

	if (!memcg || !memcg->tier2_wmark)
		return false;

	tm = memcg->tier2_wmark;

	if (!tm->enabled || memcg == root_mem_cgroup)
		return false;

	/* Update watermarks (fast path: read cached, recompute if needed) */
	tm->limit_bytes = READ_ONCE(memcg->memory.max);
	if (tm->limit_bytes == PAGE_COUNTER_MAX || tm->limit_bytes == 0)
		return false;
	tm->limit_bytes *= PAGE_SIZE;

	tm->alloc_wmark_bytes = max((unsigned long)PAGE_SIZE,
		tm->limit_bytes * (unsigned long)tm->alloc_scale / 10000UL);
	tm->demote_wmark_bytes = max(tm->alloc_wmark_bytes,
		tm->limit_bytes * (unsigned long)tm->demote_scale / 10000UL);

	headroom = tm->limit_bytes -
		(page_counter_read(&memcg->memory) * PAGE_SIZE);
	if ((long)headroom < 0)
		headroom = 0;

	demote_wmark = tm->demote_wmark_bytes;
	if (demote_wmark == 0)
		return false;

	/* Update statistics */
	if (headroom < tm->alloc_wmark_bytes) {
		atomic64_inc(&tm->below_alloc);
		atomic64_inc(&tier2_global_below_alloc);
	}
	if (headroom < demote_wmark) {
		atomic64_inc(&tm->below_demote);
		atomic64_inc(&tier2_global_below_demote);
		atomic64_inc(&tm->pressure_count);
	}

	/* Only proceed if below demote watermark */
	if (headroom >= demote_wmark)
		return false;

	/*
	 * Rate limiting: schedule async reclaim every 16th detection.
	 * This prevents workqueue flooding while ensuring timely reclaim.
	 * The actual reclaim runs asynchronously via workqueue.
	 */
	triggered = atomic64_inc_return(&tm->reclaim_triggered);
	if (triggered % 16 != 0)
		return true;  /* below_demote but skip this time */

	/*
	 * Schedule async reclaim. The workqueue handler will perform
	 * the actual reclaim, allowing the charging task to continue.
	 */
	if (!work_pending(&tm->reclaim_work))
		schedule_work(&tm->reclaim_work);

	return true;
}
EXPORT_SYMBOL_GPL(tier2_wmark_memcg_check_and_reclaim);
/* ================================================================
 * Per-memcg cgroup v1 file handlers
 * ================================================================ */

/*
 * Helper to get memcg from seq_file. Uses the same pattern as other
 * memcontrol cgroup v1 handlers.
 */
static struct mem_cgroup *tier2_memcg_from_seq(struct seq_file *m)
{
	return mem_cgroup_from_seq(m);
}

static struct mem_cgroup *tier2_memcg_from_of(struct kernfs_open_file *of)
{
	return mem_cgroup_from_css(of_css(of));
}

/* ---- memory.tier2_enabled (RW) ---- */

int tier2_memcg_enabled_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark) {
		seq_puts(m, "0\n");
		return 0;
	}

	tm = memcg->tier2_wmark;
	seq_printf(m, "%d\n", tm->enabled);
	return 0;
}

ssize_t tier2_memcg_enabled_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off)
{
	struct mem_cgroup *memcg = tier2_memcg_from_of(of);
	struct tier2_wmark_memcg *tm;
	int val, ret;

	if (!memcg || !memcg->tier2_wmark)
		return -EINVAL;

	buf = strstrip(buf);
	ret = kstrtoint(buf, 0, &val);
	if (ret < 0)
		return ret;

	if (val != 0 && val != 1)
		return -EINVAL;

	tm = memcg->tier2_wmark;
	tm->enabled = val;

	if (val)
		tier2_wmark_memcg_update(memcg);

	return nbytes;
}

/* ---- memory.tier2_alloc_scale (RW) ---- */

int tier2_memcg_alloc_scale_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark) {
		seq_printf(m, "%d\n", READ_ONCE(sysctl_tier2_alloc_scale_factor));
		return 0;
	}

	tm = memcg->tier2_wmark;
	seq_printf(m, "%d\n",
		tm->enabled ? tm->alloc_scale : READ_ONCE(sysctl_tier2_alloc_scale_factor));
	return 0;
}

ssize_t tier2_memcg_alloc_scale_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off)
{
	struct mem_cgroup *memcg = tier2_memcg_from_of(of);
	struct tier2_wmark_memcg *tm;
	int val, ret;

	if (!memcg || !memcg->tier2_wmark)
		return -EINVAL;

	buf = strstrip(buf);
	ret = kstrtoint(buf, 0, &val);
	if (ret < 0)
		return ret;

	if (val < 0 || val > 10000)
		return -EINVAL;

	tm = memcg->tier2_wmark;
	tm->alloc_scale = val;
	tier2_wmark_memcg_update(memcg);

	return nbytes;
}

/* ---- memory.tier2_demote_scale (RW) ---- */

int tier2_memcg_demote_scale_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark) {
		seq_printf(m, "%d\n", READ_ONCE(sysctl_tier2_demote_scale_factor));
		return 0;
	}

	tm = memcg->tier2_wmark;
	seq_printf(m, "%d\n",
		tm->enabled ? tm->demote_scale : READ_ONCE(sysctl_tier2_demote_scale_factor));
	return 0;
}

ssize_t tier2_memcg_demote_scale_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off)
{
	struct mem_cgroup *memcg = tier2_memcg_from_of(of);
	struct tier2_wmark_memcg *tm;
	int val, ret;

	if (!memcg || !memcg->tier2_wmark)
		return -EINVAL;

	buf = strstrip(buf);
	ret = kstrtoint(buf, 0, &val);
	if (ret < 0)
		return ret;

	if (val < 0 || val > 10000)
		return -EINVAL;

	tm = memcg->tier2_wmark;
	tm->demote_scale = val;
	tier2_wmark_memcg_update(memcg);

	return nbytes;
}

/* ---- memory.tier2_alloc_wmark (RO) ---- */

int tier2_memcg_alloc_wmark_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark) {
		seq_puts(m, "0\n");
		return 0;
	}

	tm = memcg->tier2_wmark;
	if (!tm->enabled) {
		seq_puts(m, "0\n");
		return 0;
	}

	tier2_wmark_memcg_update(memcg);
	seq_printf(m, "%lu\n", tm->alloc_wmark_bytes);
	return 0;
}

/* ---- memory.tier2_demote_wmark (RO) ---- */

int tier2_memcg_demote_wmark_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;

	if (!memcg || !memcg->tier2_wmark) {
		seq_puts(m, "0\n");
		return 0;
	}

	tm = memcg->tier2_wmark;
	if (!tm->enabled) {
		seq_puts(m, "0\n");
		return 0;
	}

	tier2_wmark_memcg_update(memcg);
	seq_printf(m, "%lu\n", tm->demote_wmark_bytes);
	return 0;
}

/* ---- memory.tier2_headroom (RO) ---- */

int tier2_memcg_headroom_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);

	if (!memcg) {
		seq_puts(m, "0\n");
		return 0;
	}

	seq_printf(m, "%lu\n", tier2_memcg_headroom_bytes(memcg));
	return 0;
}

/* ---- memory.tier2_below (RO) ---- */
/*
 * Shows below_alloc and below_demote status as comma-separated:
 * "alloc=0,demote=1"
 */
int tier2_memcg_below_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;
	unsigned long headroom;
	int alloc, demote;

	if (!memcg || !memcg->tier2_wmark) {
		seq_puts(m, "alloc=0,demote=0\n");
		return 0;
	}

	tm = memcg->tier2_wmark;
	if (!tm->enabled) {
		seq_puts(m, "alloc=0,demote=0\n");
		return 0;
	}

	headroom = tier2_memcg_headroom_bytes(memcg);
	alloc = (headroom < tm->alloc_wmark_bytes) ? 1 : 0;
	demote = (headroom < tm->demote_wmark_bytes) ? 1 : 0;

	seq_printf(m, "alloc=%d,demote=%d\n", alloc, demote);
	return 0;
}

/* ---- memory.tier2_stats (RO) ---- */

int tier2_memcg_stats_show(struct seq_file *m, void *v)
{
	struct mem_cgroup *memcg = tier2_memcg_from_seq(m);
	struct tier2_wmark_memcg *tm;
	unsigned long limit, usage, headroom;

	if (!memcg || !memcg->tier2_wmark) {
		seq_puts(m, "enabled=0\n");
		return 0;
	}

	tm = memcg->tier2_wmark;
	limit = tier2_memcg_limit_bytes(memcg);
	usage = tier2_memcg_usage_bytes(memcg);
	headroom = tier2_memcg_headroom_bytes(memcg);

	seq_printf(m, "enabled=%d\n", tm->enabled);
	seq_printf(m, "alloc_scale=%d\n",
		tm->enabled ? tm->alloc_scale : READ_ONCE(sysctl_tier2_alloc_scale_factor));
	seq_printf(m, "demote_scale=%d\n",
		tm->enabled ? tm->demote_scale : READ_ONCE(sysctl_tier2_demote_scale_factor));
	seq_printf(m, "limit_bytes=%lu\n", limit == PAGE_COUNTER_MAX ? 0UL : limit);
	seq_printf(m, "usage_bytes=%lu\n", usage);
	seq_printf(m, "headroom_bytes=%lu\n",
		headroom == ULONG_MAX ? 0UL : headroom);
	seq_printf(m, "alloc_wmark_bytes=%lu\n", tm->alloc_wmark_bytes);
	seq_printf(m, "demote_wmark_bytes=%lu\n", tm->demote_wmark_bytes);
	seq_printf(m, "below_alloc=%ld\n", (long)atomic64_read(&tm->below_alloc));
	seq_printf(m, "below_demote=%ld\n", (long)atomic64_read(&tm->below_demote));
	seq_printf(m, "reclaim_triggered=%ld\n", (long)atomic64_read(&tm->reclaim_triggered));
	seq_printf(m, "reclaim_actual=%ld\n", (long)atomic64_read(&tm->reclaim_actual));
	seq_printf(m, "reclaim_pages=%ld\n", (long)atomic64_read(&tm->reclaim_pages));
	seq_printf(m, "pressure_count=%ld\n", (long)atomic64_read(&tm->pressure_count));

	return 0;
}

/* ================================================================
 * Cgroup v1 file type definitions (NEW)
 * ================================================================
 * These are registered in mm/memcontrol-v1.c via the
 * mem_cgroup_legacy_files[] array, or added via cgroup_add_legacy_cftypes().
 *
 * We export the cftype array so it can be added to the memory cgroup
 * subsystem from the tier2 init function.
 */



MODULE_DESCRIPTION("Tier-2 Watermark for Memory Tiering");
MODULE_LICENSE("GPL");
