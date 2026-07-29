#include "myself_kswapd/kernel_snapshot_store.h"
#include "../test_support/test.h"

#include <string.h>

static struct kernel_lruvec_snapshot snapshot(
    uint64_t sequence, enum kernel_lru_mode mode, uint64_t memcg_id,
    int nid, uint32_t css_id, enum kernel_snapshot_stage stage,
    uint64_t request_id, uint64_t priority_seq, uint64_t scan_seq)
{
    return (struct kernel_lruvec_snapshot){
        .snapshot_seq = sequence,
        .timestamp_ns = sequence + 100U,
        .request_id = request_id,
        .priority_seq = priority_seq,
        .scan_seq = scan_seq,
        .key = {.mode = mode, .memcg_id = memcg_id, .nid = nid},
        .memcg_css_id = css_id,
        .reclaim_source = KERNEL_RECLAIM_MEMCG,
        .stage = stage,
        .consistency = KERNEL_SNAPSHOT_APPROXIMATE,
        .priority = 3,
        .lru_scope = mode == KERNEL_LRU_MODE_MEMCG ?
            KERNEL_SCOPE_MEMCG_NODE : KERNEL_SCOPE_NODE,
        .isolated_scope = KERNEL_SCOPE_NODE,
        .inactive_anon = sequence,
        .active_anon = sequence + 1U,
        .inactive_file = sequence + 2U,
        .active_file = sequence + 3U,
        .isolated_anon = sequence + 4U,
        .isolated_file = sequence + 5U,
        .field_valid_mask = UINT64_MAX
    };
}

static bool test_store_accepts_and_gets_latest(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot input = snapshot(
        1U, KERNEL_LRU_MODE_MEMCG, 17U, 2, 23U,
        KERNEL_SNAPSHOT_HEARTBEAT, 0U, 0U, 0U);
    struct kernel_lruvec_snapshot output;

    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &input, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(result.accepted);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &input.key, &output) == 0);
    TEST_ASSERT_EQ_U64(1U, output.snapshot_seq);
    TEST_ASSERT_EQ_U64(1U, store.count);
    kernel_snapshot_store_destroy(&store);
    return true;
}

static bool test_store_duplicate_and_stale_do_not_overwrite(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot first = snapshot(
        3U, KERNEL_LRU_MODE_MEMCG, 17U, 2, 23U,
        KERNEL_SNAPSHOT_HEARTBEAT, 0U, 0U, 0U);
    struct kernel_lruvec_snapshot duplicate = first;
    struct kernel_lruvec_snapshot stale = first;
    struct kernel_lruvec_snapshot output;

    stale.snapshot_seq = 2U;
    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &first, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &duplicate, &result) ==
                KERNEL_SNAPSHOT_DUPLICATE);
    TEST_ASSERT(!result.accepted);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &stale, &result) ==
                KERNEL_SNAPSHOT_STALE);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &first.key, &output) == 0);
    TEST_ASSERT_EQ_U64(3U, output.snapshot_seq);
    kernel_snapshot_store_destroy(&store);
    return true;
}

static bool test_store_provisional_gap_is_accepted(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot first = snapshot(
        1U, KERNEL_LRU_MODE_GLOBAL, UINT64_MAX, 2, 0U,
        KERNEL_SNAPSHOT_HEARTBEAT, 0U, 0U, 0U);
    struct kernel_lruvec_snapshot gap = first;
    struct kernel_lruvec_snapshot output;

    gap.snapshot_seq = 3U;
    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &first, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &gap, &result) ==
                KERNEL_SNAPSHOT_PROVISIONAL_GAP);
    TEST_ASSERT(result.accepted);
    TEST_ASSERT_EQ_U64(1U, result.gap_count);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &first.key, &output) == 0);
    TEST_ASSERT_EQ_U64(3U, output.snapshot_seq);
    kernel_snapshot_store_destroy(&store);
    return true;
}

static bool test_store_formal_key_dimensions_are_independent(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot mode = snapshot(
        1U, KERNEL_LRU_MODE_MEMCG, 17U, 2, 23U,
        KERNEL_SNAPSHOT_HEARTBEAT, 0U, 0U, 0U);
    struct kernel_lruvec_snapshot memcg = mode;
    struct kernel_lruvec_snapshot nid = mode;
    struct kernel_lruvec_snapshot output;

    mode.key.mode = KERNEL_LRU_MODE_GLOBAL;
    mode.key.memcg_id = UINT64_MAX;
    mode.lru_scope = KERNEL_SCOPE_NODE;
    memcg.key.memcg_id = 18U;
    memcg.memcg_css_id = 24U;
    nid.key.nid = 3;
    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &mode, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &memcg, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &nid, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT_EQ_U64(3U, store.count);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &mode.key, &output) == 0);
    TEST_ASSERT(output.key.mode == KERNEL_LRU_MODE_GLOBAL);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &memcg.key, &output) == 0);
    TEST_ASSERT_EQ_U64(18U, output.key.memcg_id);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &nid.key, &output) == 0);
    TEST_ASSERT(output.key.nid == 3);
    kernel_snapshot_store_destroy(&store);
    return true;
}

static bool test_store_stage_pairing_and_request_interleaving(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot before = snapshot(
        1U, KERNEL_LRU_MODE_MEMCG, 17U, 2, 23U,
        KERNEL_SNAPSHOT_SCAN_BEFORE, 10U, 1U, 1U);
    struct kernel_lruvec_snapshot after = before;
    struct kernel_lruvec_snapshot other_request = before;
    struct kernel_lruvec_snapshot no_before = before;

    after.snapshot_seq = 2U;
    after.stage = KERNEL_SNAPSHOT_SCAN_AFTER;
    other_request.snapshot_seq = 3U;
    other_request.request_id = 11U;
    no_before.snapshot_seq = 4U;
    no_before.request_id = 12U;
    no_before.stage = KERNEL_SNAPSHOT_SCAN_AFTER;
    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &before, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &after, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &other_request, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &no_before, &result) ==
                KERNEL_SNAPSHOT_STAGE_ORDER_ERROR);
    kernel_snapshot_store_destroy(&store);
    return true;
}

static bool test_store_rejects_css_incarnation_change(void)
{
    struct kernel_snapshot_store store;
    struct kernel_snapshot_ingest_result result;
    struct kernel_lruvec_snapshot first = snapshot(
        1U, KERNEL_LRU_MODE_MEMCG, 17U, 2, 23U,
        KERNEL_SNAPSHOT_HEARTBEAT, 0U, 0U, 0U);
    struct kernel_lruvec_snapshot changed = first;
    struct kernel_lruvec_snapshot output;

    changed.snapshot_seq = 2U;
    changed.memcg_css_id = 99U;
    kernel_snapshot_store_init(&store);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &first, &result) ==
                KERNEL_SNAPSHOT_ACCEPTED);
    TEST_ASSERT(kernel_snapshot_store_ingest(&store, &changed, &result) ==
                KERNEL_SNAPSHOT_INCARCATION_CHANGED);
    TEST_ASSERT(kernel_snapshot_store_get_latest(&store, &first.key, &output) == 0);
    TEST_ASSERT_EQ_U64(23U, output.memcg_css_id);
    kernel_snapshot_store_destroy(&store);
    return true;
}

void register_test_kernel_snapshot_store(void)
{
    reclaim_test_register("snapshot store accepted latest", test_store_accepts_and_gets_latest);
    reclaim_test_register("snapshot store duplicate stale", test_store_duplicate_and_stale_do_not_overwrite);
    reclaim_test_register("snapshot store provisional gap", test_store_provisional_gap_is_accepted);
    reclaim_test_register("snapshot store formal key", test_store_formal_key_dimensions_are_independent);
    reclaim_test_register("snapshot store stage pairing", test_store_stage_pairing_and_request_interleaving);
    reclaim_test_register("snapshot store CSS incarnation", test_store_rejects_css_incarnation_change);
}
