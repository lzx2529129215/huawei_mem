/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_TIER2_WATERMARK_H
#define _LINUX_TIER2_WATERMARK_H

#include <linux/mmzone.h>
#include <linux/mm.h>
#include <linux/atomic.h>
#include <linux/jiffies.h>
#include <linux/seq_file.h>
#include <linux/kernfs.h>

struct mem_cgroup;

#ifdef CONFIG_TIER2_WATERMARK

/* ================================================================
 * Per-node statistics (unchanged from original)
 * ================================================================ */

struct tier2_wmark_stats {
	atomic64_t below_alloc;
	atomic64_t below_demote;
	atomic64_t reclaim_wakeup;
	atomic64_t reclaim_target_adj;
	atomic64_t demote_attempt;
	atomic64_t demote_success;
	atomic64_t demote_fail;
	atomic64_t promotion_hint;
	atomic64_t promotion_success;
	atomic64_t pingpong_suspect;
};

struct tier2_wmark_ewma {
	unsigned long ewma_free_pages;
	unsigned long last_update_jiffies;
	unsigned long last_free_pages;
};

struct tier2_wmark_node {
	struct tier2_wmark_stats stats;
	struct tier2_wmark_ewma ewma;
};

/* ================================================================
 * Per-memcg tier2 watermark state (NEW)
 * ================================================================
 * Each memory cgroup can have its own tier2 watermark configuration.
 * When enabled, watermarks are calculated based on the memcg's
 * memory.limit_in_bytes instead of the node's managed_pages.
 *
 * headroom = limit_bytes - current_usage_bytes
 * alloc_wmark = max(limit * alloc_scale / 10000, page_size)
 * demote_wmark = max(alloc_wmark, limit * demote_scale / 10000)
 * below_alloc  = (headroom < alloc_wmark)
 * below_demote = (headroom < demote_wmark)
 *
 * If limit is unlimited (PAGE_COUNTER_MAX), per-memcg tier2 is disabled
 * and falls back to global node-level watermarks.
 */
struct tier2_wmark_memcg {
	/* Configuration: writable by userspace */
	int		enabled;	/* 0=use global, 1=per-memcg */
	int		alloc_scale;	/* alloc scale in 1/10000 (default 100 = 1%) */
	int		demote_scale;	/* demote scale in 1/10000 (default 300 = 3%) */

	/* Computed watermarks (in bytes), updated on config change */
	unsigned long	alloc_wmark_bytes;
	unsigned long	demote_wmark_bytes;
	unsigned long	limit_bytes;	/* cached limit for watermark calc */

	/* Per-memcg statistics */
	atomic64_t	below_alloc;
	atomic64_t	below_demote;
	atomic64_t	reclaim_triggered;  /* total below_demote detections */
	atomic64_t	reclaim_actual;     /* actual reclaim invocations (rate-limited) */
	atomic64_t	reclaim_pages;      /* total pages reclaimed (cumulative) */
	atomic64_t	pressure_count;     /* reclaim pressure events counter */

	/* Back-pointer for workqueue access */
	struct mem_cgroup *memcg;

	/* Async reclaim work item */
	struct work_struct reclaim_work;
};

/* ================================================================
 * Node-level API (unchanged)
 * ================================================================ */

bool tier2_wmark_enabled(void);
unsigned long tier2_wmark_alloc_pages_pgdat(struct pglist_data *pgdat);
unsigned long tier2_wmark_demote_pages_pgdat(struct pglist_data *pgdat);
bool tier2_wmark_below_alloc(struct pglist_data *pgdat);
bool tier2_wmark_below_demote(struct pglist_data *pgdat);
void tier2_wmark_record_below(struct pglist_data *pgdat);
void tier2_wmark_record_reclaim_wakeup(struct pglist_data *pgdat);
void tier2_wmark_record_demote_attempt(struct pglist_data *pgdat, unsigned long nr_pages);
void tier2_wmark_record_demote_result(struct pglist_data *pgdat, unsigned long success, unsigned long fail);
void tier2_wmark_update_ewma(struct pglist_data *pgdat);
int tier2_wmark_state_show(struct seq_file *m, void *v);

extern int sysctl_tier2_wmark_enabled;
extern int sysctl_tier2_alloc_scale_factor;
extern int sysctl_tier2_demote_scale_factor;

/* ================================================================
 * Per-memcg API (NEW)
 * ================================================================ */

/* Allocate and initialize per-memcg tier2 state (incl workqueue) */
int tier2_wmark_memcg_alloc(struct mem_cgroup *memcg);

/* Free per-memcg tier2 state (cancel pending work) */
void tier2_wmark_memcg_free(struct mem_cgroup *memcg);

/* Update per-memcg watermarks based on current limit */
void tier2_wmark_memcg_update(struct mem_cgroup *memcg);

/* Check and record per-memcg watermark status (observation only).
 * Returns true if below demote watermark. */
bool tier2_wmark_memcg_check(struct mem_cgroup *memcg);

/* Check watermarks AND schedule async reclaim if needed.
 * Called from done_restock in try_charge_memcg().
 * Uses workqueue for async reclaim to avoid blocking the charge path.
 * Returns true if reclaim work was scheduled. */
bool tier2_wmark_memcg_check_and_reclaim(struct mem_cgroup *memcg);
bool tier2_wmark_memcg_check_and_reclaim(struct mem_cgroup *memcg);

/* ================================================================
 * Per-memcg cgroup v1 file show/write handlers (NEW)
 * ================================================================ */

int tier2_memcg_enabled_show(struct seq_file *m, void *v);
ssize_t tier2_memcg_enabled_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off);

int tier2_memcg_alloc_scale_show(struct seq_file *m, void *v);
ssize_t tier2_memcg_alloc_scale_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off);

int tier2_memcg_demote_scale_show(struct seq_file *m, void *v);
ssize_t tier2_memcg_demote_scale_write(struct kernfs_open_file *of,
		char *buf, size_t nbytes, loff_t off);

int tier2_memcg_alloc_wmark_show(struct seq_file *m, void *v);
int tier2_memcg_demote_wmark_show(struct seq_file *m, void *v);
int tier2_memcg_headroom_show(struct seq_file *m, void *v);
int tier2_memcg_below_show(struct seq_file *m, void *v);
int tier2_memcg_stats_show(struct seq_file *m, void *v);

#else /* !CONFIG_TIER2_WATERMARK */

/* Node-level stubs */
static inline bool tier2_wmark_enabled(void) { return false; }
static inline unsigned long tier2_wmark_alloc_pages_pgdat(struct pglist_data *pgdat) { return 0; }
static inline unsigned long tier2_wmark_demote_pages_pgdat(struct pglist_data *pgdat) { return 0; }
static inline bool tier2_wmark_below_alloc(struct pglist_data *pgdat) { return false; }
static inline bool tier2_wmark_below_demote(struct pglist_data *pgdat) { return false; }
static inline void tier2_wmark_record_below(struct pglist_data *pgdat) { }
static inline void tier2_wmark_record_reclaim_wakeup(struct pglist_data *pgdat) { }
static inline void tier2_wmark_record_demote_attempt(struct pglist_data *pgdat, unsigned long nr_pages) { }
static inline void tier2_wmark_record_demote_result(struct pglist_data *pgdat, unsigned long s, unsigned long f) { }
static inline void tier2_wmark_update_ewma(struct pglist_data *pgdat) { }

/* Per-memcg stubs */
static inline int tier2_wmark_memcg_alloc(struct mem_cgroup *memcg) { return 0; }
static inline void tier2_wmark_memcg_free(struct mem_cgroup *memcg) { }
static inline void tier2_wmark_memcg_update(struct mem_cgroup *memcg) { }
static inline bool tier2_wmark_memcg_check(struct mem_cgroup *memcg) { return false; }
static inline bool tier2_wmark_memcg_check_and_reclaim(struct mem_cgroup *memcg) { return false; }

#endif /* CONFIG_TIER2_WATERMARK */
#endif /* _LINUX_TIER2_WATERMARK_H */
