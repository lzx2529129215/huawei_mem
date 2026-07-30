#include "myself_kswapd/shadow_alignment.h"

#include <errno.h>
#include <string.h>

int shadow_engine_lookup_lruvec_stats(
    struct reclaim_engine *engine,
    uint64_t memcg_id,
    int nid,
    struct shadow_lruvec_stats *out)
{
    return shadow_lruvec_get_stats(engine, memcg_id, nid, out);
}

static uint64_t kernel_count(const struct kernel_lruvec_snapshot *snapshot,
                             int index)
{
    const uint64_t counts[SHADOW_LRU_NR] = {
        snapshot->inactive_anon, snapshot->active_anon,
        snapshot->inactive_file, snapshot->active_file
    };
    return counts[index];
}

int shadow_alignment_compare(
    struct reclaim_engine *engine,
    const struct kernel_lruvec_snapshot *snapshot,
    struct shadow_alignment_result *result)
{
    struct shadow_lruvec_stats shadow;
    uint64_t kernel_isolated;
    int error;
    int index;

    if (engine == NULL || snapshot == NULL || result == NULL) return -EINVAL;
    *result = (struct shadow_alignment_result){.snapshot_seq = snapshot->snapshot_seq};
    if (snapshot->snapshot_seq == 0U) {
        result->status = SHADOW_ALIGNMENT_STALE_KERNEL_SNAPSHOT;
        return result->status;
    }
    error = shadow_engine_lookup_lruvec_stats(engine, snapshot->key.memcg_id,
                                               snapshot->key.nid, &shadow);
    if (error == RECLAIM_ERR_DOMAIN_NOT_FOUND) {
        result->status = SHADOW_ALIGNMENT_MISSING_SHADOW_LRUVEC;
        return result->status;
    }
    if (error != RECLAIM_OK) return -error;
    for (index = 0; index < SHADOW_LRU_NR; index++) {
        result->delta[index] = (int64_t)kernel_count(snapshot, index) -
                                (int64_t)shadow.nr_pages[index];
    }
    // #lzx: node-scoped isolated counts do not suppress ordinary LRU drift.
    if (snapshot->key.mode == KERNEL_LRU_MODE_MEMCG &&
        snapshot->isolated_scope == KERNEL_SCOPE_NODE) {
        result->isolated_comparable = 0;
        for (index = 0; index < SHADOW_LRU_NR; index++) {
            if (result->delta[index] != 0) {
                result->status = SHADOW_ALIGNMENT_COUNT_DRIFT;
                return result->status;
            }
        }
        result->status = SHADOW_ALIGNMENT_FIELD_NOT_COMPARABLE;
        return result->status;
    }
    kernel_isolated = snapshot->isolated_anon + snapshot->isolated_file;
    result->isolated_delta = (int64_t)kernel_isolated -
                             (int64_t)shadow.nr_isolated;
    result->isolated_comparable = 1;
    result->status = SHADOW_ALIGNMENT_MATCH;
    for (index = 0; index < SHADOW_LRU_NR; index++) {
        if (result->delta[index] != 0) {
            result->status = SHADOW_ALIGNMENT_COUNT_DRIFT;
            break;
        }
    }
    if (result->status == SHADOW_ALIGNMENT_MATCH && result->isolated_delta != 0)
        result->status = SHADOW_ALIGNMENT_COUNT_DRIFT;
    return result->status;
}
