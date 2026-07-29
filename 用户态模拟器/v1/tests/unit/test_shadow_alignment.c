#include "myself_kswapd/shadow_alignment.h"
#include "myself_kswapd/executor.h"
#include "myself_kswapd/platform.h"
#include "../test_support/test.h"

#include <stdint.h>

static struct reclaim_engine *make_engine(struct reclaim_userspace_platform *platform,
                                          struct reclaim_simulator_executor *executor)
{
    const struct reclaim_engine_config config = {
        .default_swappiness = 60U,
        .default_swap_enabled = true,
        .pressure = {.default_priority = 2U, .minimum_priority = 0U,
                     .scan_batch_pages = 4U, .max_reclaim_rounds = 3U},
        .page_hash_buckets = 8U, .domain_hash_buckets = 8U,
    };
    struct reclaim_engine *engine = NULL;

    reclaim_platform_userspace_init(platform);
    reclaim_simulator_executor_init(executor);
    if (reclaim_engine_create(&platform->platform, &config,
                              reclaim_g1_aging_ops(),
                              reclaim_simulator_executor_ops(), executor,
                              &engine) != RECLAIM_OK)
        return NULL;
    return engine;
}

static bool add_four_pages(struct reclaim_engine *engine)
{
    const enum shadow_lru_type lrus[4] = {
        SHADOW_LRU_INACTIVE_ANON, SHADOW_LRU_ACTIVE_ANON,
        SHADOW_LRU_INACTIVE_FILE, SHADOW_LRU_ACTIVE_FILE
    };
    unsigned i;

    if (shadow_engine_create_domain(engine, 17U) != RECLAIM_OK) return false;
    for (i = 0U; i < 4U; i++) {
        struct shadow_page_add_event event = {
            .event_seq = i + 1U, .page_id = i + 1U, .memcg_id = 17U,
            .nid = 2, .lru = lrus[i],
            .page_type = i < 2U ? RECLAIM_PAGE_ANON : RECLAIM_PAGE_FILE,
            .order = 0U,
        };
        if (shadow_page_add(engine, &event) != RECLAIM_OK) return false;
    }
    return true;
}

static struct kernel_lruvec_snapshot alignment_snapshot(enum kernel_lru_mode mode)
{
    return (struct kernel_lruvec_snapshot){
        .snapshot_seq = 1U, .key = {.mode = mode,
            .memcg_id = mode == KERNEL_LRU_MODE_MEMCG ? 17U : UINT64_MAX,
            .nid = 2}, .memcg_css_id = mode == KERNEL_LRU_MODE_MEMCG ? 23U : 0U,
        .stage = KERNEL_SNAPSHOT_DEBUGFS, .lru_scope =
            mode == KERNEL_LRU_MODE_MEMCG ? KERNEL_SCOPE_MEMCG_NODE : KERNEL_SCOPE_NODE,
        .isolated_scope = KERNEL_SCOPE_NODE,
        .consistency = KERNEL_SNAPSHOT_APPROXIMATE,
    };
}

static bool test_shadow_lookup_does_not_create(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = make_engine(&platform, &executor);
    struct shadow_lruvec_stats stats;

    TEST_ASSERT(engine != NULL);
    TEST_ASSERT(shadow_engine_lookup_lruvec_stats(engine, 77U, 2, &stats) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    TEST_ASSERT(reclaim_engine_get_domain_stats(engine, 77U,
                                                &(struct reclaim_domain_stats){0}) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    reclaim_engine_destroy(engine);
    return true;
}

static bool test_shadow_alignment_match_and_drift(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = make_engine(&platform, &executor);
    struct shadow_alignment_result result;
    struct kernel_lruvec_snapshot snapshot;

    TEST_ASSERT(engine != NULL && add_four_pages(engine));
    snapshot = alignment_snapshot(KERNEL_LRU_MODE_GLOBAL);
    snapshot.key.memcg_id = 17U;
    snapshot.inactive_anon = 1U;
    snapshot.active_anon = 1U;
    snapshot.inactive_file = 1U;
    snapshot.active_file = 1U;
    TEST_ASSERT(shadow_alignment_compare(engine, &snapshot, &result) ==
                SHADOW_ALIGNMENT_MATCH);
    snapshot.active_anon = 2U;
    TEST_ASSERT(shadow_alignment_compare(engine, &snapshot, &result) ==
                SHADOW_ALIGNMENT_COUNT_DRIFT);
    TEST_ASSERT(result.delta[SHADOW_LRU_ACTIVE_ANON] == 1);
    reclaim_engine_destroy(engine);
    return true;
}

static bool test_memcg_isolated_not_comparable_and_missing_stale(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = make_engine(&platform, &executor);
    struct shadow_alignment_result result;
    struct kernel_lruvec_snapshot snapshot;

    TEST_ASSERT(engine != NULL && add_four_pages(engine));
    snapshot = alignment_snapshot(KERNEL_LRU_MODE_MEMCG);
    snapshot.inactive_anon = 1U;
    snapshot.active_anon = 1U;
    snapshot.inactive_file = 1U;
    snapshot.active_file = 1U;
    TEST_ASSERT(shadow_alignment_compare(engine, &snapshot, &result) ==
                SHADOW_ALIGNMENT_FIELD_NOT_COMPARABLE);
    snapshot.snapshot_seq = 0U;
    TEST_ASSERT(shadow_alignment_compare(engine, &snapshot, &result) ==
                SHADOW_ALIGNMENT_STALE_KERNEL_SNAPSHOT);
    snapshot.snapshot_seq = 1U;
    snapshot.key.memcg_id = 99U;
    TEST_ASSERT(shadow_alignment_compare(engine, &snapshot, &result) ==
                SHADOW_ALIGNMENT_MISSING_SHADOW_LRUVEC);
    reclaim_engine_destroy(engine);
    return true;
}

void register_test_shadow_alignment(void)
{
    reclaim_test_register("Shadow read-only lookup", test_shadow_lookup_does_not_create);
    reclaim_test_register("Shadow alignment match and drift", test_shadow_alignment_match_and_drift);
    reclaim_test_register("Shadow alignment isolated and missing", test_memcg_isolated_not_comparable_and_missing_stale);
}
