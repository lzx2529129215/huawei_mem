/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_PARP_H
#define _LINUX_PARP_H

#include <linux/types.h>
#include <linux/jump_label.h>

struct folio;
struct lruvec;
struct scan_control;
struct mem_cgroup;
struct damon_ctx;
struct damon_target;
struct damon_region;
struct page_ext_operations;

enum parp_frontier_mode {
	PARP_FRONTIER_OFF,
	PARP_FRONTIER_SHADOW,
	PARP_FRONTIER_APPLY,
};

enum parp_frontier_reason {
	PARP_FRONTIER_SCORE,
	PARP_FRONTIER_DISABLED,
	PARP_FRONTIER_NOT_TARGET_MEMCG,
	PARP_FRONTIER_PRESSURE_BYPASS,
	PARP_FRONTIER_NO_APP_CONTEXT,
	PARP_FRONTIER_NO_EFFICIENCY,
	PARP_FRONTIER_NO_DEMAND,
	PARP_FRONTIER_NO_CAPACITY,
	PARP_FRONTIER_NOT_FRONTIER,
	PARP_FRONTIER_METADATA_MISSING,
	PARP_FRONTIER_MODEL_INVALID,
	PARP_FRONTIER_BELOW_THRESHOLD,
	PARP_FRONTIER_BUDGET,
	PARP_FRONTIER_REPEAT_EPOCH,
	PARP_FRONTIER_EXPIRED,
};

struct parp_frontier_scan_ctx {
	bool valid;
	u8 type;
	u8 mode;
	u8 reason;
	u32 model_version;
	u32 threshold;
	u32 efficiency_q15;
	u32 app_reentry_q15;
	u32 app_id;
	u32 nid;
	u32 source_generation;
	u64 domain_id;
	u64 epoch_id;
	u64 batch_id;
	u64 foreground_epoch_id;
	u64 valid_until_ns;
	unsigned long source_seq;
	unsigned long frontier_seq;
	unsigned long remaining_demand;
	unsigned long frontier_headroom;
	unsigned long app_budget;
	unsigned long batch_budget;
	unsigned long epoch_budget;
	unsigned long batch_used;
	unsigned long app_used;
};

enum parp_mode {
	PARP_MODE_DISABLED,
	PARP_MODE_OBSERVE,
	PARP_MODE_APPLY,
};

enum parp_action {
	PARP_ACTION_NATIVE,
	PARP_ACTION_PROTECT,
	PARP_ACTION_RECLAIM_BIAS,
	PARP_ACTION_PREFETCH_CANDIDATE,
};

enum parp_fallback_reason {
	PARP_FALLBACK_NONE,
	PARP_FALLBACK_DISABLED,
	PARP_FALLBACK_NO_DOMAIN,
	PARP_FALLBACK_NO_BINDING,
	PARP_FALLBACK_EXPIRED,
	PARP_FALLBACK_MODEL_VERSION,
	PARP_FALLBACK_NO_EVIDENCE,
	PARP_FALLBACK_UNSAFE_FOLIO,
	PARP_FALLBACK_EVIDENCE_ONLY,
	PARP_FALLBACK_NR,
};

struct parp_decision {
	enum parp_action original_action;
	enum parp_action proposed_action;
	enum parp_action applied_action;
	enum parp_fallback_reason fallback;
	u16 score_q15;
};

struct parp_reclaim_ctx {
	u64 domain_id;
	const void *snapshot;
	enum parp_mode mode;
	bool rcu_held;
};

enum parp_scan_budget_mode {
	PARP_SCAN_BUDGET_DISABLED,
	PARP_SCAN_BUDGET_OBSERVE,
	PARP_SCAN_BUDGET_APPLY,
};

enum parp_reclaim_scope {
	PARP_RECLAIM_SCOPE_UNKNOWN,
	PARP_RECLAIM_SCOPE_GLOBAL_KSWAPD,
	PARP_RECLAIM_SCOPE_GLOBAL_DIRECT,
	PARP_RECLAIM_SCOPE_TARGET_MEMCG,
	PARP_RECLAIM_SCOPE_PROACTIVE_MEMCG,
	PARP_RECLAIM_SCOPE_MEMCG_HIGH,
};

enum parp_pressure_level {
	PARP_PRESSURE_NORMAL,
	PARP_PRESSURE_ELEVATED,
	PARP_PRESSURE_HIGH,
	PARP_PRESSURE_EMERGENCY,
};

enum parp_scan_budget_reason {
	PARP_SCAN_REASON_NATIVE,
	PARP_SCAN_REASON_FOREGROUND,
	PARP_SCAN_REASON_HIGH_PRIOR,
	PARP_SCAN_REASON_MEDIUM_PRIOR,
	PARP_SCAN_REASON_LOW_PRIOR,
	PARP_SCAN_REASON_NO_BIND,
	PARP_SCAN_REASON_STALE_BIND,
	PARP_SCAN_REASON_NO_PRIOR,
	PARP_SCAN_REASON_EXPIRED_PRIOR,
	PARP_SCAN_REASON_STALE_GENERATION,
	PARP_SCAN_REASON_MODEL_VERSION,
	PARP_SCAN_REASON_NOT_TARGET_MEMCG,
	PARP_SCAN_REASON_PRESSURE_BYPASS,
	PARP_SCAN_REASON_CIRCUIT_BREAKER,
	PARP_SCAN_REASON_CLAMP_MIN,
	PARP_SCAN_REASON_CLAMP_MAX,
	PARP_SCAN_REASON_APPLY_DOMAIN,
	PARP_SCAN_REASON_DISABLED,
};

struct parp_scan_budget_decision {
	bool valid;
	u64 native_nr_to_scan;
	u64 proposed_nr_to_scan;
	u64 applied_nr_to_scan;
	u32 multiplier_q15;
	u16 confidence_q15;
	enum parp_scan_budget_reason reason;
	u32 reason_flags;
	u64 budget_sequence;
};

#ifdef CONFIG_PARP
void parp_adapter_prepare(struct parp_reclaim_ctx *ctx,
			  struct lruvec *lruvec, struct scan_control *sc);
struct parp_decision
parp_adapter_score_folio(struct parp_reclaim_ctx *ctx, struct folio *folio,
			 int type, int generation);
void parp_adapter_apply_decision(struct parp_reclaim_ctx *ctx,
				 struct folio *folio,
				 struct parp_decision *decision);
void parp_adapter_finish(struct parp_reclaim_ctx *ctx,
			 unsigned long scanned, unsigned long isolated);
bool parp_adapter_prepare_scan_budget(struct lruvec *lruvec,
				      struct mem_cgroup *target_memcg,
				      bool global_kswapd, bool proactive,
				      int reclaim_priority,
				      unsigned long native_nr_to_scan,
				      struct parp_scan_budget_decision *decision);
unsigned long parp_adapter_apply_scan_budget(
				const struct parp_scan_budget_decision *decision);
#ifdef CONFIG_PARP_DAMON_ALIGNMENT
void parp_damon_aggregate(struct damon_ctx *ctx, struct damon_target *target,
			  struct damon_region *region);
#else
static inline void parp_damon_aggregate(struct damon_ctx *ctx,
					struct damon_target *target,
					struct damon_region *region)
{
}
#endif

#ifdef CONFIG_PARP_FRONTIER_SCORE
extern struct static_key_false parp_frontier_enabled;
extern struct page_ext_operations parp_frontier_page_ext_ops;

void __parp_frontier_note_access(struct folio *folio, int generation);
void __parp_frontier_prepare(struct parp_frontier_scan_ctx *ctx,
		struct lruvec *lruvec, bool target_memcg, int type,
		int reclaim_priority, int reclaim_idx,
		unsigned long remaining_demand);
void __parp_frontier_consider(struct parp_frontier_scan_ctx *ctx,
		struct lruvec *lruvec, struct folio *folio);
void parp_frontier_feedback(struct lruvec *lruvec, int type,
		unsigned long isolated, unsigned long reclaimed);
enum parp_frontier_mode parp_frontier_get_mode(void);
int parp_frontier_set_mode(enum parp_frontier_mode mode);
ssize_t parp_frontier_format_stats(char *buf, size_t size);

static inline void parp_frontier_note_access(struct folio *folio,
					     int generation)
{
	if (static_branch_unlikely(&parp_frontier_enabled))
		__parp_frontier_note_access(folio, generation);
}

static inline void parp_frontier_prepare(struct parp_frontier_scan_ctx *ctx,
		struct lruvec *lruvec, bool target_memcg, int type,
		int reclaim_priority, int reclaim_idx,
		unsigned long remaining_demand)
{
	if (static_branch_unlikely(&parp_frontier_enabled))
		__parp_frontier_prepare(ctx, lruvec, target_memcg, type,
				reclaim_priority, reclaim_idx, remaining_demand);
	else
		ctx->valid = false;
}

static inline void parp_frontier_consider(struct parp_frontier_scan_ctx *ctx,
					  struct lruvec *lruvec,
					  struct folio *folio)
{
	if (static_branch_unlikely(&parp_frontier_enabled))
		__parp_frontier_consider(ctx, lruvec, folio);
}
#else
static inline void parp_frontier_note_access(struct folio *folio,
					     int generation)
{
}
static inline void parp_frontier_prepare(struct parp_frontier_scan_ctx *ctx,
		struct lruvec *lruvec, bool target_memcg, int type,
		int reclaim_priority, int reclaim_idx,
		unsigned long remaining_demand)
{
	ctx->valid = false;
}
static inline void parp_frontier_consider(struct parp_frontier_scan_ctx *ctx,
					  struct lruvec *lruvec,
					  struct folio *folio)
{
}
static inline void parp_frontier_feedback(struct lruvec *lruvec, int type,
		unsigned long isolated, unsigned long reclaimed)
{
}
#endif
#else
static inline void parp_adapter_prepare(struct parp_reclaim_ctx *ctx,
					struct lruvec *lruvec,
					struct scan_control *sc)
{
	ctx->mode = PARP_MODE_DISABLED;
	ctx->rcu_held = false;
}

static inline struct parp_decision
parp_adapter_score_folio(struct parp_reclaim_ctx *ctx, struct folio *folio,
			 int type, int generation)
{
	return (struct parp_decision) {
		.original_action = PARP_ACTION_NATIVE,
		.proposed_action = PARP_ACTION_NATIVE,
		.applied_action = PARP_ACTION_NATIVE,
		.fallback = PARP_FALLBACK_DISABLED,
	};
}

static inline void
parp_adapter_apply_decision(struct parp_reclaim_ctx *ctx, struct folio *folio,
			    struct parp_decision *decision)
{
}

static inline void parp_adapter_finish(struct parp_reclaim_ctx *ctx,
				       unsigned long scanned,
				       unsigned long isolated)
{
}
static inline bool parp_adapter_prepare_scan_budget(
		struct lruvec *lruvec, struct mem_cgroup *target_memcg,
		bool global_kswapd, bool proactive, int reclaim_priority,
		unsigned long native_nr_to_scan,
		struct parp_scan_budget_decision *decision)
{
	*decision = (struct parp_scan_budget_decision) {
		.native_nr_to_scan = native_nr_to_scan,
		.proposed_nr_to_scan = native_nr_to_scan,
		.applied_nr_to_scan = native_nr_to_scan,
		.reason = PARP_SCAN_REASON_DISABLED,
	};
	return false;
}

static inline unsigned long parp_adapter_apply_scan_budget(
		const struct parp_scan_budget_decision *decision)
{
	return decision->native_nr_to_scan;
}
static inline void parp_damon_aggregate(struct damon_ctx *ctx,
					struct damon_target *target,
					struct damon_region *region)
{
}
static inline void parp_frontier_note_access(struct folio *folio,
					     int generation)
{
}
static inline void parp_frontier_prepare(struct parp_frontier_scan_ctx *ctx,
		struct lruvec *lruvec, bool target_memcg, int type,
		int reclaim_priority, int reclaim_idx,
		unsigned long remaining_demand)
{
	ctx->valid = false;
}
static inline void parp_frontier_consider(struct parp_frontier_scan_ctx *ctx,
					  struct lruvec *lruvec,
					  struct folio *folio)
{
}
static inline void parp_frontier_feedback(struct lruvec *lruvec, int type,
		unsigned long isolated, unsigned long reclaimed)
{
}
#endif
#endif
