#include "myself_kswapd/kernel_snapshot_store.h"
#include "../test_support/test.h"

#include <stdint.h>

static struct kernel_lruvec_snapshot bootstrap_snapshot(uint64_t sequence)
{
    return (struct kernel_lruvec_snapshot){
        .snapshot_seq = sequence,
        .timestamp_ns = sequence,
        .key = {.mode = KERNEL_LRU_MODE_GLOBAL, .memcg_id = UINT64_MAX, .nid = 2},
        .memcg_css_id = 0,
        .reclaim_source = KERNEL_RECLAIM_UNKNOWN,
        .stage = KERNEL_SNAPSHOT_DEBUGFS,
        .consistency = KERNEL_SNAPSHOT_APPROXIMATE,
        .priority = -1,
        .lru_scope = KERNEL_SCOPE_NODE,
        .isolated_scope = KERNEL_SCOPE_NODE,
        .inactive_anon = sequence
    };
}

static bool test_bootstrap_is_independent_and_latest(void)
{
    struct kernel_bootstrap_aggregate baseline;
    struct kernel_lruvec_snapshot input = bootstrap_snapshot(1U);
    struct kernel_lruvec_snapshot output;

    kernel_bootstrap_aggregate_init(&baseline);
    TEST_ASSERT(kernel_bootstrap_aggregate_update(&baseline, &input) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT_EQ_U64(1U, baseline.accepted_count);
    TEST_ASSERT_EQ_U64(1U, baseline.store.count);
    TEST_ASSERT(kernel_bootstrap_aggregate_get_latest(&baseline, &input.key,
                                                      &output) == 0);
    TEST_ASSERT_EQ_U64(1U, output.snapshot_seq);
    kernel_bootstrap_aggregate_destroy(&baseline);
    return true;
}

static bool test_bootstrap_preserves_store_statuses(void)
{
    struct kernel_bootstrap_aggregate baseline;
    struct kernel_lruvec_snapshot input = bootstrap_snapshot(1U);

    kernel_bootstrap_aggregate_init(&baseline);
    TEST_ASSERT(kernel_bootstrap_aggregate_update(&baseline, &input) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_bootstrap_aggregate_update(&baseline, &input) ==
                KERNEL_SNAPSHOT_DUPLICATE);
    TEST_ASSERT_EQ_U64(1U, baseline.rejected_count);
    TEST_ASSERT_EQ_U64(1U, baseline.store.count);
    kernel_bootstrap_aggregate_destroy(&baseline);
    return true;
}

void register_test_bootstrap_aggregate(void)
{
    reclaim_test_register("bootstrap aggregate isolation", test_bootstrap_is_independent_and_latest);
    reclaim_test_register("bootstrap aggregate store status", test_bootstrap_preserves_store_statuses);
}
