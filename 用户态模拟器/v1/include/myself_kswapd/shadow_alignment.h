#ifndef MYSELF_KSWAPD_SHADOW_ALIGNMENT_H
#define MYSELF_KSWAPD_SHADOW_ALIGNMENT_H

#include "myself_kswapd/kernel_lruvec_snapshot.h"
#include "myself_kswapd/shadow_lru.h"

#include <stdint.h>

enum shadow_alignment_status {
    SHADOW_ALIGNMENT_MATCH = 0,
    SHADOW_ALIGNMENT_COUNT_DRIFT,
    SHADOW_ALIGNMENT_MISSING_SHADOW_LRUVEC,
    SHADOW_ALIGNMENT_MISSING_KERNEL_LRUVEC,
    SHADOW_ALIGNMENT_STALE_KERNEL_SNAPSHOT,
    SHADOW_ALIGNMENT_MEMCG_INCARCATION_CHANGED,
    SHADOW_ALIGNMENT_FIELD_NOT_COMPARABLE,
    SHADOW_ALIGNMENT_UNSUPPORTED_PAGE_LEVEL_COMPARE,
    SHADOW_ALIGNMENT_UNSUPPORTED_MGLRU
};

struct shadow_alignment_result {
    enum shadow_alignment_status status;
    int64_t delta[SHADOW_LRU_NR];
    int64_t isolated_delta;
    uint64_t snapshot_seq;
    int isolated_comparable;
};

int shadow_engine_lookup_lruvec_stats(
    struct reclaim_engine *engine,
    uint64_t memcg_id,
    int nid,
    struct shadow_lruvec_stats *out);
int shadow_alignment_compare(
    struct reclaim_engine *engine,
    const struct kernel_lruvec_snapshot *snapshot,
    struct shadow_alignment_result *result);

#endif
