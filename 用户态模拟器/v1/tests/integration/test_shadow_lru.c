// #lzx: per-memcg-per-node Shadow LRU implementation

#define _XOPEN_SOURCE 700

#include "myself_kswapd/shadow_lru.h"
#include "myself_kswapd/executor.h"
#include "myself_kswapd/validator.h"
#include "../../src/core/internal.h"
#include "../test_support/test.h"

static bool test_shadow_lru_reverse_move_concurrency(void);

#include <pthread.h>

// #lzx--------------------------- Shadow LRU 生命周期测试 ---------------------------
static bool test_shadow_lru_sparse_nodes_and_lifecycle(void)
{
    struct reclaim_userspace_platform platform; // #lzx
    struct reclaim_simulator_executor executor; // #lzx
    struct reclaim_engine *engine = NULL; // #lzx
    struct shadow_page_add_event add = { // #lzx
        .page_id = 100U, // #lzx
        .memcg_id = 7U, // #lzx
        .nid = 2, // #lzx
        .lru = SHADOW_LRU_INACTIVE_FILE, // #lzx
        .page_type = RECLAIM_PAGE_FILE, // #lzx
        .order = 0U, // #lzx
    }; // #lzx
    struct shadow_page_isolate_event isolate = { // #lzx
        .page_id = 100U, // #lzx
        .memcg_id = 7U, // #lzx
        .nid = 2, // #lzx
        .source_lru = SHADOW_LRU_INACTIVE_FILE, // #lzx
        .page_type = RECLAIM_PAGE_FILE, // #lzx
    }; // #lzx
    struct shadow_page_putback_event putback = { // #lzx
        .page_id = 100U, // #lzx
        .target_memcg_id = 7U, // #lzx
        .target_nid = 0, // #lzx
        .target_lru = SHADOW_LRU_ACTIVE_FILE, // #lzx
    }; // #lzx
    struct shadow_page_info info; // #lzx
    struct shadow_lruvec_stats node_zero; // #lzx
    struct shadow_lruvec_stats node_two; // #lzx

    reclaim_platform_userspace_init(&platform); // #lzx
    reclaim_simulator_executor_init(&executor); // #lzx
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_engine_create_domain(engine, 7U) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &add) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 7U, 2, &node_two) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 7U, 1, &node_zero) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_putback(engine, &putback) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_get_info(engine, 100U, &info) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(7U, info.memcg_id);
    TEST_ASSERT_EQ_U64(0U, (uint64_t)info.nid);
    TEST_ASSERT(info.state == SHADOW_PAGE_ON_LRU);
    TEST_ASSERT(info.current_lru == SHADOW_LRU_ACTIVE_FILE);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 7U, 0, &node_zero) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(1U, node_zero.nr_pages[SHADOW_LRU_ACTIVE_FILE]);
    TEST_ASSERT_EQ_U64(0U, node_two.nr_isolated);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow LRU 生命周期测试结束 ---------------------------

// #lzx--------------------------- Shadow LRU 乱序与自愈测试 ---------------------------
static bool test_shadow_lru_event_order_and_reclaim(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_page_isolate_event isolate = {
        .event_seq = 100U, .page_id = 200U, .memcg_id = 8U, .nid = 2,
        .source_lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_page_add_event delayed_add = {
        .event_seq = 90U, .page_id = 200U, .memcg_id = 8U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE, .order = 1U,
    };
    struct shadow_page_putback_event putback = {
        .event_seq = 102U, .page_id = 200U, .target_memcg_id = 8U, .target_nid = 0,
        .target_lru = SHADOW_LRU_ACTIVE_FILE,
    };
    struct shadow_page_reclaimed_event reclaim = {.event_seq = 103U, .page_id = 200U};
    struct shadow_page_reclaimed_event unknown = {.event_seq = 104U, .page_id = 201U};
    struct shadow_page_info info;
    struct shadow_lruvec_stats stats;
    uint64_t flags;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_get_info(engine, 200U, &info) == RECLAIM_OK);
    TEST_ASSERT(info.provisional);
    TEST_ASSERT(info.state == SHADOW_PAGE_ISOLATED);
    TEST_ASSERT(info.isolated_from == SHADOW_LRU_ORIGIN_INACTIVE_FILE);
    TEST_ASSERT(info.putback_hint == SHADOW_LRU_INACTIVE_FILE);
    TEST_ASSERT(shadow_page_add(engine, &delayed_add) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_get_info(engine, 200U, &info) == RECLAIM_OK);
    TEST_ASSERT(!info.provisional);
    TEST_ASSERT(info.state == SHADOW_PAGE_ISOLATED);
    TEST_ASSERT_EQ_U64(100U, info.last_event_seq);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    isolate.event_seq = 101U;
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_putback(engine, &putback) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 8U, 0, &stats) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(2U, stats.nr_pages[SHADOW_LRU_ACTIVE_FILE]);
    TEST_ASSERT(shadow_page_reclaimed(engine, &reclaim) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_get_info(engine, 200U, &info) == RECLAIM_ERR_PAGE_NOT_FOUND);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 8U, 0, &stats) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(0U, stats.nr_pages[SHADOW_LRU_ACTIVE_FILE]);
    TEST_ASSERT(shadow_page_reclaimed(engine, &unknown) == RECLAIM_OK);
    flags = shadow_engine_validation_flags(engine);
    TEST_ASSERT((flags & SHADOW_VALIDATION_ISOLATE_UNKNOWN_PAGE) != 0U);
    TEST_ASSERT((flags & SHADOW_VALIDATION_STALE_EVENT) != 0U);
    TEST_ASSERT((flags & SHADOW_VALIDATION_DUPLICATE_EVENT) != 0U);
    TEST_ASSERT((flags & SHADOW_VALIDATION_DUPLICATE_ISOLATE) != 0U);
    TEST_ASSERT((flags & SHADOW_VALIDATION_PUTBACK_HINT_MISMATCH) != 0U);
    TEST_ASSERT((flags & SHADOW_VALIDATION_RECLAIM_UNKNOWN_PAGE) != 0U);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    TEST_ASSERT(shadow_engine_destroy_domain(engine, 8U) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 8U, 0, &stats) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow LRU 乱序与自愈测试结束 ---------------------------

// #lzx--------------------------- Sequence gate 拓扑副作用测试 ---------------------------
static bool test_shadow_lru_stale_duplicate_do_not_create_targets(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_page_add_event add = {
        .event_seq = 100U, .page_id = 250U, .memcg_id = 1U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_move_event move = {
        .event_seq = 99U, .page_id = 250U,
        .source_memcg_id = 1U, .source_nid = 0, .source_state = SHADOW_PAGE_ON_LRU,
        .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 2U, .target_nid = 2, .target_lru = SHADOW_LRU_ACTIVE_ANON,
        .reason = SHADOW_MOVE_MEMCG_AND_NUMA, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_putback_event putback = {
        .event_seq = 99U, .page_id = 250U, .target_memcg_id = 3U, .target_nid = 3,
        .target_lru = SHADOW_LRU_INACTIVE_ANON,
    };
    struct shadow_page_isolate_event isolate = {
        .event_seq = 99U, .page_id = 250U, .memcg_id = 4U, .nid = 4,
        .source_lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_lruvec_stats stats;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &add) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_move(engine, &move) == RECLAIM_OK);
    move.event_seq = 100U;
    TEST_ASSERT(shadow_page_move(engine, &move) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 2U, 2, &stats) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    TEST_ASSERT(shadow_page_putback(engine, &putback) == RECLAIM_OK);
    putback.event_seq = 100U;
    TEST_ASSERT(shadow_page_putback(engine, &putback) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 3U, 3, &stats) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    isolate.event_seq = 100U;
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 4U, 4, &stats) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    move.event_seq = 101U;
    TEST_ASSERT(shadow_page_move(engine, &move) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 2U, 2, &stats) == RECLAIM_OK);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Sequence gate 拓扑副作用测试结束 ---------------------------

// #lzx--------------------------- Shadow LRU 迁移与节点扫描测试 ---------------------------
static bool test_shadow_lru_move_and_node_scan(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_page_add_event first = {
        .page_id = 300U, .memcg_id = 1U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_add_event second = {
        .page_id = 301U, .memcg_id = 1U, .nid = 0,
        .lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_page_add_event third = {
        .page_id = 302U, .memcg_id = 2U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_page_move_event move = {
        .event_seq = 10U, .page_id = 300U,
        .source_memcg_id = 1U, .source_nid = 0, .source_state = SHADOW_PAGE_ON_LRU,
        .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 2U, .target_nid = 2, .target_lru = SHADOW_LRU_ACTIVE_ANON,
        .reason = SHADOW_MOVE_MEMCG_AND_NUMA, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_isolate_event isolate = {
        .event_seq = 11U, .page_id = 301U, .memcg_id = 1U, .nid = 0,
        .source_lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_page_move_event move_isolated = {
        .event_seq = 12U, .page_id = 301U,
        .source_memcg_id = 1U, .source_nid = 0, .source_state = SHADOW_PAGE_ISOLATED,
        .source_lru = SHADOW_LRU_ACTIVE_FILE,
        .target_memcg_id = 2U, .target_nid = 2, .target_lru = SHADOW_LRU_INACTIVE_FILE,
        .reason = SHADOW_MOVE_MEMCG_AND_NUMA, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_scan_request request = {.max_pages = 16U, .max_candidates = 16U};
    struct shadow_node_scan_request node_request = {
        .max_pages_per_domain = 16U, .max_candidates_per_domain = 16U,
    };
    struct shadow_scan_result scan;
    struct shadow_node_scan_result node_scan;
    struct shadow_page_info info;
    struct shadow_lruvec_stats old_stats;
    struct shadow_lruvec_stats target_stats;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &first) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &second) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &third) == RECLAIM_OK);
    TEST_ASSERT(shadow_scan_lruvec(engine, 1U, 2, &request, &scan) ==
                RECLAIM_ERR_DOMAIN_NOT_FOUND);
    TEST_ASSERT(shadow_scan_node(engine, 0, &node_request, &node_scan) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(2U, node_scan.nr_domains_considered);
    TEST_ASSERT_EQ_U64(2U, node_scan.nr_domains_scanned);
    TEST_ASSERT_EQ_U64(3U, node_scan.nr_pages_scanned);
    TEST_ASSERT_EQ_U64(2U, node_scan.nr_candidates_selected);
    TEST_ASSERT(shadow_page_move(engine, &move) == RECLAIM_OK);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 1U, 0, &old_stats) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(0U, old_stats.nr_pages[SHADOW_LRU_INACTIVE_ANON]);
    TEST_ASSERT_EQ_U64(1U, old_stats.nr_move_out);
    TEST_ASSERT(shadow_lruvec_get_stats(engine, 2U, 2, &target_stats) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(1U, target_stats.nr_pages[SHADOW_LRU_ACTIVE_ANON]);
    TEST_ASSERT_EQ_U64(1U, target_stats.nr_move_in);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_move(engine, &move_isolated) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_get_info(engine, 301U, &info) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(2U, info.memcg_id);
    TEST_ASSERT_EQ_U64(2U, (uint64_t)info.nid);
    TEST_ASSERT(info.state == SHADOW_PAGE_ISOLATED);
    TEST_ASSERT(info.isolated_from == SHADOW_LRU_ORIGIN_ACTIVE_FILE);
    TEST_ASSERT(info.putback_hint == SHADOW_LRU_INACTIVE_FILE);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow LRU 迁移与节点扫描测试结束 ---------------------------

// #lzx--------------------------- Shadow 候选快照与重验证测试 ---------------------------
static bool test_shadow_lru_candidates_revalidate(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_page_add_event add = {
        .event_seq = 1U, .page_id = 350U, .memcg_id = 9U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_isolate_event isolate = {
        .event_seq = 2U, .page_id = 350U, .memcg_id = 9U, .nid = 0,
        .source_lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_candidate_request request = {.max_pages = 8U, .max_candidates = 8U};
    struct shadow_candidate candidates[1];
    struct shadow_candidate_result collected;
    struct shadow_candidate_validation validation;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &add) == RECLAIM_OK);
    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 9U, 0, &request, candidates,
                                                  1U, &collected) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(1U, collected.nr_candidates);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidates[0], &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_VALID);
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidates[0], &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_STATE_CHANGED ||
                validation.status == SHADOW_CANDIDATE_EVENT_SEQ_CHANGED);
    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 9U, 0, &request, candidates,
                                                  1U, &collected) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(0U, collected.nr_candidates);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow 候选快照与重验证测试结束 ---------------------------

// #lzx--------------------------- Shadow 候选完整收集矩阵测试 ---------------------------
static bool test_shadow_lru_candidate_collection_matrix(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    const struct shadow_page_add_event adds[] = {
        {.page_id = 1000U, .memcg_id = 40U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.page_id = 1001U, .memcg_id = 40U, .nid = 0,
         .lru = SHADOW_LRU_ACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.page_id = 1002U, .memcg_id = 40U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE},
        {.page_id = 1003U, .memcg_id = 40U, .nid = 0,
         .lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE},
        {.page_id = 1004U, .memcg_id = 40U, .nid = 1,
         .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE},
        {.page_id = 1005U, .memcg_id = 41U, .nid = 0,
         .lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE},
        {.page_id = 1006U, .memcg_id = 40U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE},
    };
    const struct shadow_page_isolate_event isolate = {
        .event_seq = 20U, .page_id = 1006U, .memcg_id = 40U, .nid = 0,
        .source_lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    const struct shadow_candidate_request unlimited = {
        .max_pages = 0U, .max_candidates = 0U,
    };
    struct shadow_candidate candidates[8];
    struct shadow_candidate_result result;
    size_t index;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    for (index = 0U; index < sizeof(adds) / sizeof(adds[0]); index++) {
        TEST_ASSERT(shadow_page_add(engine, &adds[index]) == RECLAIM_OK);
    }
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);

    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 40U, 0, &unlimited,
                                                  NULL, 0U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(4U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(0U, result.nr_candidates);
    TEST_ASSERT(result.truncated);

    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 40U, 0, &unlimited,
                                                  candidates, 2U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(4U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(2U, result.nr_candidates);
    TEST_ASSERT_EQ_U64(2U, result.nr_truncated);
    TEST_ASSERT(result.truncated);

    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 40U, 0, &unlimited,
                                                  candidates, 4U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(4U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(4U, result.nr_candidates);
    TEST_ASSERT(!result.truncated);

    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 40U, 0, &unlimited,
                                                  candidates, 8U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(4U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(4U, result.nr_candidates);
    TEST_ASSERT(!result.truncated);

    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 40U, 1, &unlimited,
                                                  candidates, 8U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(1U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(1U, result.nr_candidates);
    TEST_ASSERT_EQ_U64(1004U, candidates[0].page_id);
    TEST_ASSERT(shadow_collect_lruvec_candidates(engine, 41U, 0, &unlimited,
                                                  candidates, 8U, &result) == RECLAIM_OK);
    TEST_ASSERT_EQ_U64(1U, result.nr_total_eligible);
    TEST_ASSERT_EQ_U64(1U, result.nr_candidates);
    TEST_ASSERT_EQ_U64(1005U, candidates[0].page_id);

    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow 候选完整收集矩阵测试结束 ---------------------------

static bool shadow_test_mark_page_dying(struct reclaim_engine *engine, uint64_t page_id)
{
    size_t bucket;
    struct shadow_page *page;

    pthread_mutex_lock(&engine->shadow_page_table_lock);
    for (bucket = 0U; bucket < engine->shadow_pages.bucket_count; bucket++) {
        for (page = engine->shadow_pages.buckets[bucket]; page != NULL;
             page = page->hash_next) {
            if (page->page_id == page_id) {
                page->dying = true;
                pthread_mutex_unlock(&engine->shadow_page_table_lock);
                return true;
            }
        }
    }
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    return false;
}

static bool shadow_test_collect_one(struct reclaim_engine *engine,
                                    uint64_t memcg_id,
                                    int nid,
                                    struct shadow_candidate *candidate)
{
    const struct shadow_candidate_request request = {
        .max_pages = 1U, .max_candidates = 1U,
    };
    struct shadow_candidate_result result;

    if (shadow_collect_lruvec_candidates(engine, memcg_id, nid, &request,
                                         candidate, 1U, &result) != RECLAIM_OK ||
        result.nr_candidates != 1U) {
        return false;
    }
    return true;
}

static struct shadow_page *shadow_test_find_page(struct reclaim_engine *engine,
                                                  uint64_t page_id)
{
    size_t bucket;
    struct shadow_page *page;

    pthread_mutex_lock(&engine->shadow_page_table_lock);
    for (bucket = 0U; bucket < engine->shadow_pages.bucket_count; bucket++) {
        for (page = engine->shadow_pages.buckets[bucket]; page != NULL;
             page = page->hash_next) {
            if (page->page_id == page_id) {
                pthread_mutex_unlock(&engine->shadow_page_table_lock);
                return page;
            }
        }
    }
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    return NULL;
}

// #lzx--------------------------- Shadow 候选失效矩阵测试 ---------------------------
static bool test_shadow_lru_candidate_invalidation_matrix(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    const struct shadow_page_add_event adds[] = {
        {.event_seq = 1U, .page_id = 1100U, .memcg_id = 60U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 2U, .page_id = 1101U, .memcg_id = 62U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 3U, .page_id = 1102U, .memcg_id = 64U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 4U, .page_id = 1103U, .memcg_id = 66U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 5U, .page_id = 1104U, .memcg_id = 68U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 6U, .page_id = 1105U, .memcg_id = 70U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 7U, .page_id = 1106U, .memcg_id = 72U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
        {.event_seq = 8U, .page_id = 1107U, .memcg_id = 74U, .nid = 0,
         .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON},
    };
    const struct shadow_page_move_event move_nid = {
        .event_seq = 20U, .page_id = 1100U,
        .source_memcg_id = 60U, .source_nid = 0,
        .source_state = SHADOW_PAGE_ON_LRU, .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 60U, .target_nid = 1,
        .target_lru = SHADOW_LRU_INACTIVE_ANON,
        .reason = SHADOW_MOVE_NUMA, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_move_event move_memcg = {
        .event_seq = 21U, .page_id = 1101U,
        .source_memcg_id = 62U, .source_nid = 0,
        .source_state = SHADOW_PAGE_ON_LRU, .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 63U, .target_nid = 0,
        .target_lru = SHADOW_LRU_INACTIVE_ANON,
        .reason = SHADOW_MOVE_MEMCG, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_move_event move_both = {
        .event_seq = 22U, .page_id = 1102U,
        .source_memcg_id = 64U, .source_nid = 0,
        .source_state = SHADOW_PAGE_ON_LRU, .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 65U, .target_nid = 1,
        .target_lru = SHADOW_LRU_INACTIVE_ANON,
        .reason = SHADOW_MOVE_MEMCG_AND_NUMA, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_isolate_event isolate = {
        .event_seq = 23U, .page_id = 1103U, .memcg_id = 66U, .nid = 0,
        .source_lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_move_event move_lru = {
        .event_seq = 24U, .page_id = 1104U,
        .source_memcg_id = 68U, .source_nid = 0,
        .source_state = SHADOW_PAGE_ON_LRU, .source_lru = SHADOW_LRU_INACTIVE_ANON,
        .target_memcg_id = 68U, .target_nid = 0,
        .target_lru = SHADOW_LRU_ACTIVE_ANON,
        .reason = SHADOW_MOVE_MEMCG_AND_NUMA, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_add_event refresh_seq = {
        .event_seq = 25U, .page_id = 1105U, .memcg_id = 70U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    const struct shadow_page_reclaimed_event reclaim = {
        .event_seq = 26U, .page_id = 1107U,
    };
    struct shadow_candidate candidate;
    struct shadow_candidate_validation validation;
    size_t index;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    for (index = 0U; index < sizeof(adds) / sizeof(adds[0]); index++) {
        TEST_ASSERT(shadow_page_add(engine, &adds[index]) == RECLAIM_OK);
    }

    TEST_ASSERT(shadow_test_collect_one(engine, 60U, 0, &candidate));
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_VALID);
    TEST_ASSERT(shadow_page_move(engine, &move_nid) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_LOCATION_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 62U, 0, &candidate));
    TEST_ASSERT(shadow_page_move(engine, &move_memcg) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_LOCATION_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 64U, 0, &candidate));
    TEST_ASSERT(shadow_page_move(engine, &move_both) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_LOCATION_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 66U, 0, &candidate));
    TEST_ASSERT(shadow_page_isolate(engine, &isolate) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_STATE_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 68U, 0, &candidate));
    TEST_ASSERT(shadow_page_move(engine, &move_lru) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_LRU_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 70U, 0, &candidate));
    TEST_ASSERT(shadow_page_add(engine, &refresh_seq) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_EVENT_SEQ_CHANGED);

    TEST_ASSERT(shadow_test_collect_one(engine, 72U, 0, &candidate));
    TEST_ASSERT(shadow_test_mark_page_dying(engine, 1106U));
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_PAGE_DYING);

    TEST_ASSERT(shadow_test_collect_one(engine, 74U, 0, &candidate));
    TEST_ASSERT(shadow_page_reclaimed(engine, &reclaim) == RECLAIM_OK);
    TEST_ASSERT(shadow_candidate_revalidate(engine, &candidate, &validation) == RECLAIM_OK);
    TEST_ASSERT(validation.status == SHADOW_CANDIDATE_PAGE_MISSING);

    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow 候选失效矩阵测试结束 ---------------------------

// #lzx--------------------------- Shadow validator 双向故障注入测试 ---------------------------
static bool test_shadow_lru_validator_bidirectional_faults(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    const struct shadow_page_add_event add = {
        .event_seq = 1U, .page_id = 1200U, .memcg_id = 80U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct reclaim_validation_report report;
    struct shadow_page *page;
    struct shadow_page *isolated_page;
    struct shadow_lruvec *lruvec;
    struct shadow_lruvec *isolated_lruvec;
    struct shadow_domain *domain;
    enum shadow_lru_type lru;
    struct shadow_page **saved_table_cursor = NULL;
    struct shadow_page *saved_hash_next = NULL;
    struct reclaim_list_node orphan = {0};
    size_t bucket;
    uint64_t flags;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &add) == RECLAIM_OK);
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_OK);
    page = shadow_test_find_page(engine, 1200U);
    TEST_ASSERT(page != NULL);
    lruvec = page->container;
    lru = page->current_lru;

    /* Chain entry exists, but the page-table reverse edge is removed. */
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    for (bucket = 0U; bucket < engine->shadow_pages.bucket_count; bucket++) {
        struct shadow_page **cursor;
        for (cursor = &engine->shadow_pages.buckets[bucket]; *cursor != NULL;
             cursor = &(*cursor)->hash_next) {
            if (*cursor == page) {
                saved_table_cursor = cursor;
                saved_hash_next = page->hash_next;
                *cursor = page->hash_next;
                page->hash_next = NULL;
                break;
            }
        }
        if (saved_table_cursor != NULL) {
            break;
        }
    }
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    TEST_ASSERT(saved_table_cursor != NULL);
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    *saved_table_cursor = page;
    page->hash_next = saved_hash_next;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    /* Table entry says linked, but no chain contains the page. */
    reclaim_list_remove(&lruvec->lists[lru], &page->list_node);
    lruvec->nr_pages[lru]--;
    page->list_node.list = &lruvec->lists[lru];
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    flags = shadow_engine_validation_flags(engine);
    TEST_ASSERT((flags & SHADOW_VALIDATION_CHAIN_STATE_MISMATCH) != 0U);
    page->list_node.list = NULL;
    reclaim_list_push_back(&lruvec->lists[lru], &page->list_node);
    lruvec->nr_pages[lru]++;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    /* A second chain node names the same page; matching counters must not hide it. */
    orphan.owner = page;
    reclaim_list_push_back(&lruvec->lists[lru], &orphan);
    lruvec->nr_pages[lru]++;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    reclaim_list_remove(&lruvec->lists[lru], &orphan);
    lruvec->nr_pages[lru]--;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    page->memcg_id = 81U;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    page->memcg_id = 80U;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    page->nid = 1;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    page->nid = 0;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    page->current_lru = SHADOW_LRU_NR;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    page->current_lru = lru;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    lruvec->nr_pages[lru]++;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    lruvec->nr_pages[lru]--;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    lruvec->nid = 1;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    lruvec->nid = 0;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    page->state = SHADOW_PAGE_ISOLATED;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    page->state = SHADOW_PAGE_ON_LRU;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    page->dying = true;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    page->dying = false;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    domain = page->domain;
    domain->memcg_id = 81U;
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
    domain->memcg_id = 80U;
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    {
        const struct shadow_page_add_event isolated_add = {
            .event_seq = 2U, .page_id = 1201U, .memcg_id = 80U, .nid = 0,
            .lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
        };
        const struct shadow_page_isolate_event isolated_event = {
            .event_seq = 3U, .page_id = 1201U, .memcg_id = 80U, .nid = 0,
            .source_lru = SHADOW_LRU_ACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
        };
        const struct shadow_page_putback_event isolated_putback = {
            .event_seq = 4U, .page_id = 1201U, .target_memcg_id = 80U,
            .target_nid = 0, .target_lru = SHADOW_LRU_ACTIVE_FILE,
        };
        TEST_ASSERT(shadow_page_add(engine, &isolated_add) == RECLAIM_OK);
        TEST_ASSERT(shadow_page_isolate(engine, &isolated_event) == RECLAIM_OK);
        isolated_page = shadow_test_find_page(engine, 1201U);
        TEST_ASSERT(isolated_page != NULL);
        isolated_lruvec = isolated_page->container;
        isolated_lruvec->nr_isolated++;
        TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_VALIDATION);
        isolated_lruvec->nr_isolated--;
        TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
        TEST_ASSERT(shadow_page_putback(engine, &isolated_putback) == RECLAIM_OK);
        TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    }

    /* Temporary validator collections must fail closed on allocation failure. */
    reclaim_platform_userspace_set_fail_after(&platform, 0L);
    TEST_ASSERT(shadow_engine_validate(engine, &report) == RECLAIM_ERR_NO_MEMORY);
    reclaim_platform_userspace_set_fail_after(&platform, -1L);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);

    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow validator 双向故障注入测试结束 ---------------------------

// #lzx--------------------------- Shadow 确定性交错并发测试 ---------------------------
enum shadow_interleave_operation {
    SHADOW_INTERLEAVE_MOVE,
    SHADOW_INTERLEAVE_ISOLATE,
    SHADOW_INTERLEAVE_PUTBACK,
};

struct shadow_interleave_context {
    struct reclaim_engine *engine;
    pthread_barrier_t barrier;
    enum shadow_interleave_operation operation;
    bool scan_holds_before_phase;
    bool event_holds_before_phase;
    uint64_t scan_memcg;
    int scan_nid;
    struct shadow_lruvec *scan_lruvec;
    struct shadow_lruvec *event_left_lruvec;
    struct shadow_lruvec *event_right_lruvec;
    struct shadow_page_move_event move;
    struct shadow_page_isolate_event isolate;
    struct shadow_page_putback_event putback;
    struct shadow_scan_result scan_result;
    int scan_error;
    int event_error;
};

static bool shadow_test_barrier_wait(pthread_barrier_t *barrier)
{
    int result = pthread_barrier_wait(barrier);

    return result == 0 || result == PTHREAD_BARRIER_SERIAL_THREAD;
}

static struct shadow_lruvec *shadow_test_find_lruvec(struct reclaim_engine *engine,
                                                      uint64_t memcg_id,
                                                      int nid)
{
    size_t bucket;
    struct shadow_domain *domain;

    for (bucket = 0U; bucket < engine->shadow_domains.bucket_count; bucket++) {
        for (domain = engine->shadow_domains.buckets[bucket]; domain != NULL;
             domain = domain->hash_next) {
            size_t node_bucket;
            if (domain->memcg_id != memcg_id) {
                continue;
            }
            for (node_bucket = 0U; node_bucket < domain->node_table.bucket_count; node_bucket++) {
                struct shadow_lruvec *lruvec;
                for (lruvec = domain->node_table.buckets[node_bucket]; lruvec != NULL;
                     lruvec = lruvec->hash_next) {
                    if (lruvec->nid == nid) {
                        return lruvec;
                    }
                }
            }
        }
    }
    return NULL;
}

static void shadow_test_lock_event_lruvecs(struct shadow_interleave_context *context)
{
    if (context->event_left_lruvec == context->event_right_lruvec) {
        pthread_mutex_lock(&context->event_left_lruvec->lock);
    } else {
        pthread_mutex_lock(&context->event_left_lruvec->lock);
        pthread_mutex_lock(&context->event_right_lruvec->lock);
    }
}

static void shadow_test_unlock_event_lruvecs(struct shadow_interleave_context *context)
{
    if (context->event_left_lruvec == context->event_right_lruvec) {
        pthread_mutex_unlock(&context->event_left_lruvec->lock);
    } else {
        pthread_mutex_unlock(&context->event_right_lruvec->lock);
        pthread_mutex_unlock(&context->event_left_lruvec->lock);
    }
}

static void *shadow_interleave_scan_worker(void *argument)
{
    struct shadow_interleave_context *context = argument;
    const struct shadow_scan_request request = {.max_pages = 16U, .max_candidates = 16U};

    if (!shadow_test_barrier_wait(&context->barrier)) {
        context->scan_error = RECLAIM_ERR_INTERNAL;
        return (void *)1;
    }
    if (context->scan_holds_before_phase) {
        pthread_mutex_lock(&context->scan_lruvec->lock);
        if (!shadow_test_barrier_wait(&context->barrier)) {
            pthread_mutex_unlock(&context->scan_lruvec->lock);
            context->scan_error = RECLAIM_ERR_INTERNAL;
            return (void *)1;
        }
        pthread_mutex_unlock(&context->scan_lruvec->lock);
    } else if (!shadow_test_barrier_wait(&context->barrier)) {
        context->scan_error = RECLAIM_ERR_INTERNAL;
        return (void *)1;
    }
    context->scan_error = shadow_scan_lruvec(context->engine, context->scan_memcg,
                                             context->scan_nid, &request,
                                             &context->scan_result);
    return NULL;
}

static void *shadow_interleave_event_worker(void *argument)
{
    struct shadow_interleave_context *context = argument;

    if (!shadow_test_barrier_wait(&context->barrier)) {
        context->event_error = RECLAIM_ERR_INTERNAL;
        return (void *)1;
    }
    if (context->event_holds_before_phase) {
        shadow_test_lock_event_lruvecs(context);
        if (!shadow_test_barrier_wait(&context->barrier)) {
            shadow_test_unlock_event_lruvecs(context);
            context->event_error = RECLAIM_ERR_INTERNAL;
            return (void *)1;
        }
        shadow_test_unlock_event_lruvecs(context);
    } else if (!shadow_test_barrier_wait(&context->barrier)) {
        context->event_error = RECLAIM_ERR_INTERNAL;
        return (void *)1;
    }
    switch (context->operation) {
    case SHADOW_INTERLEAVE_MOVE:
        context->event_error = shadow_page_move(context->engine, &context->move);
        break;
    case SHADOW_INTERLEAVE_ISOLATE:
        context->event_error = shadow_page_isolate(context->engine, &context->isolate);
        break;
    case SHADOW_INTERLEAVE_PUTBACK:
        context->event_error = shadow_page_putback(context->engine, &context->putback);
        break;
    }
    return context->event_error == RECLAIM_OK ? NULL : (void *)1;
}

static bool shadow_test_run_scan_interleave(enum shadow_interleave_operation operation,
                                             bool scan_first)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_interleave_context context = {0};
    struct shadow_candidate candidate;
    struct shadow_candidate_validation validation;
    const struct shadow_page_add_event add = {
        .event_seq = 1U, .page_id = 1300U + (uint64_t)operation,
        .memcg_id = 90U + (uint64_t)operation, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    const struct shadow_page_add_event target_add = {
        .event_seq = 2U, .page_id = 1310U + (uint64_t)operation,
        .memcg_id = 90U + (uint64_t)operation, .nid = 1,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    const struct shadow_page_reclaimed_event target_reclaim = {
        .event_seq = 3U, .page_id = 1310U + (uint64_t)operation,
    };
    pthread_t scan_thread;
    pthread_t event_thread;
    void *scan_result = NULL;
    void *event_result = NULL;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    if (reclaim_engine_create(&platform.platform, NULL, NULL,
                              reclaim_simulator_executor_ops(), &executor, &engine) !=
        RECLAIM_OK) {
        return false;
    }
    if (shadow_page_add(engine, &add) != RECLAIM_OK) {
        reclaim_engine_destroy(engine);
        return false;
    }
    if (operation == SHADOW_INTERLEAVE_MOVE &&
        (shadow_page_add(engine, &target_add) != RECLAIM_OK ||
         shadow_page_reclaimed(engine, &target_reclaim) != RECLAIM_OK)) {
        reclaim_engine_destroy(engine);
        return false;
    }
    context.engine = engine;
    context.operation = operation;
    context.scan_memcg = add.memcg_id;
    context.scan_nid = add.nid;
    context.scan_lruvec = shadow_test_find_lruvec(engine, add.memcg_id, add.nid);
    context.event_left_lruvec = context.scan_lruvec;
    context.event_right_lruvec = context.scan_lruvec;
    context.scan_holds_before_phase = scan_first;
    context.event_holds_before_phase = !scan_first;
    context.move = (struct shadow_page_move_event){
        .event_seq = 10U, .page_id = add.page_id,
        .source_memcg_id = add.memcg_id, .source_nid = 0,
        .source_state = SHADOW_PAGE_ON_LRU, .source_lru = add.lru,
        .target_memcg_id = add.memcg_id, .target_nid = 1,
        .target_lru = SHADOW_LRU_ACTIVE_FILE,
        .reason = SHADOW_MOVE_NUMA, .page_type = RECLAIM_PAGE_FILE,
    };
    context.isolate = (struct shadow_page_isolate_event){
        .event_seq = 10U, .page_id = add.page_id,
        .memcg_id = add.memcg_id, .nid = add.nid,
        .source_lru = add.lru, .page_type = add.page_type,
    };
    context.putback = (struct shadow_page_putback_event){
        .event_seq = 11U, .page_id = add.page_id,
        .target_memcg_id = add.memcg_id, .target_nid = add.nid,
        .target_lru = add.lru,
    };
    if (operation == SHADOW_INTERLEAVE_MOVE) {
        context.event_right_lruvec = shadow_test_find_lruvec(engine, add.memcg_id, 1);
    } else if (operation == SHADOW_INTERLEAVE_PUTBACK) {
        struct shadow_page_isolate_event setup_isolate = context.isolate;
        setup_isolate.event_seq = 4U;
        if (!shadow_test_collect_one(engine, add.memcg_id, add.nid, &candidate) ||
            shadow_page_isolate(engine, &setup_isolate) != RECLAIM_OK) {
            reclaim_engine_destroy(engine);
            return false;
        }
    } else if (!shadow_test_collect_one(engine, add.memcg_id, add.nid, &candidate)) {
        reclaim_engine_destroy(engine);
        return false;
    }
    if (operation == SHADOW_INTERLEAVE_MOVE &&
        !shadow_test_collect_one(engine, add.memcg_id, add.nid, &candidate)) {
        reclaim_engine_destroy(engine);
        return false;
    }
    if (pthread_barrier_init(&context.barrier, NULL, 2U) != 0 ||
        pthread_create(&scan_thread, NULL, shadow_interleave_scan_worker, &context) != 0 ||
        pthread_create(&event_thread, NULL, shadow_interleave_event_worker, &context) != 0) {
        reclaim_engine_destroy(engine);
        return false;
    }
    (void)pthread_join(scan_thread, &scan_result);
    (void)pthread_join(event_thread, &event_result);
    pthread_barrier_destroy(&context.barrier);
    if (scan_result != NULL || event_result != NULL || context.scan_error != RECLAIM_OK ||
        context.event_error != RECLAIM_OK || shadow_engine_validate(engine, NULL) != RECLAIM_OK ||
        shadow_candidate_revalidate(engine, &candidate, &validation) != RECLAIM_OK ||
        validation.status == SHADOW_CANDIDATE_VALID) {
        reclaim_engine_destroy(engine);
        return false;
    }
    reclaim_engine_destroy(engine);
    return reclaim_platform_userspace_live_allocations(&platform) == 0U;
}

struct shadow_reclaim_race_context {
    struct reclaim_engine *engine;
    pthread_barrier_t barrier;
    bool move;
    struct shadow_page_putback_event putback_event;
    struct shadow_page_move_event move_event;
    struct shadow_page_reclaimed_event reclaim_event;
};

struct shadow_reclaim_race_worker {
    struct shadow_reclaim_race_context *context;
    bool reclaim;
};

static void *shadow_reclaim_race_worker(void *argument)
{
    struct shadow_reclaim_race_worker *worker = argument;
    struct shadow_reclaim_race_context *context = worker->context;
    int error;

    if (!shadow_test_barrier_wait(&context->barrier)) {
        return (void *)1;
    }
    if (worker->reclaim) {
        error = shadow_page_reclaimed(context->engine, &context->reclaim_event);
    } else if (context->move) {
        error = shadow_page_move(context->engine, &context->move_event);
    } else {
        error = shadow_page_putback(context->engine, &context->putback_event);
    }
    return error == RECLAIM_OK ? NULL : (void *)1;
}

static bool shadow_test_run_reclaim_race(bool putback)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    const struct shadow_page_add_event add = {
        .event_seq = 1U, .page_id = putback ? 1401U : 1400U,
        .memcg_id = 100U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    const struct shadow_page_isolate_event isolate = {
        .event_seq = 2U, .page_id = putback ? 1401U : 1400U,
        .memcg_id = 100U, .nid = 0,
        .source_lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    struct shadow_reclaim_race_context context = {0};
    pthread_t first_thread;
    pthread_t second_thread;
    struct shadow_reclaim_race_worker first_worker;
    struct shadow_reclaim_race_worker second_worker;
    void *first_result = NULL;
    void *second_result = NULL;
    struct shadow_page_info info;
    int info_error;
    bool state_invalid;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    if (reclaim_engine_create(&platform.platform, NULL, NULL,
                              reclaim_simulator_executor_ops(), &executor, &engine) !=
        RECLAIM_OK || shadow_page_add(engine, &add) != RECLAIM_OK ||
        shadow_page_isolate(engine, &isolate) != RECLAIM_OK) {
        reclaim_engine_destroy(engine);
        return false;
    }
    context.engine = engine;
    context.move = !putback;
    context.putback_event = (struct shadow_page_putback_event){
        .event_seq = 10U, .page_id = add.page_id,
        .target_memcg_id = 100U, .target_nid = 0,
        .target_lru = SHADOW_LRU_ACTIVE_FILE,
    };
    context.reclaim_event = (struct shadow_page_reclaimed_event){
        .event_seq = 11U, .page_id = add.page_id,
    };
    context.move_event = (struct shadow_page_move_event){
        .event_seq = 10U, .page_id = add.page_id,
        .source_memcg_id = 100U, .source_nid = 0,
        .source_state = SHADOW_PAGE_ISOLATED, .source_lru = add.lru,
        .target_memcg_id = 100U, .target_nid = 0,
        .target_lru = SHADOW_LRU_ACTIVE_FILE,
        .reason = SHADOW_MOVE_NUMA, .page_type = RECLAIM_PAGE_FILE,
    };
    first_worker = (struct shadow_reclaim_race_worker){
        .context = &context, .reclaim = false,
    };
    second_worker = (struct shadow_reclaim_race_worker){
        .context = &context, .reclaim = true,
    };
    if (pthread_barrier_init(&context.barrier, NULL, 2U) != 0 ||
        pthread_create(&first_thread, NULL, shadow_reclaim_race_worker, &first_worker) != 0 ||
        pthread_create(&second_thread, NULL, shadow_reclaim_race_worker, &second_worker) != 0) {
        reclaim_engine_destroy(engine);
        return false;
    }
    (void)pthread_join(first_thread, &first_result);
    (void)pthread_join(second_thread, &second_result);
    pthread_barrier_destroy(&context.barrier);
    info_error = shadow_page_get_info(engine, add.page_id, &info);
    state_invalid = info_error == RECLAIM_OK &&
                    ((putback && info.state != SHADOW_PAGE_ON_LRU) ||
                     (!putback && info.state != SHADOW_PAGE_ISOLATED));
    if (first_result != NULL || second_result != NULL ||
        (info_error != RECLAIM_OK && info_error != RECLAIM_ERR_PAGE_NOT_FOUND) ||
        state_invalid || shadow_engine_validate(engine, NULL) != RECLAIM_OK) {
        reclaim_engine_destroy(engine);
        return false;
    }
    reclaim_engine_destroy(engine);
    return reclaim_platform_userspace_live_allocations(&platform) == 0U;
}

struct shadow_domain_destroy_context {
    struct reclaim_engine *engine;
    pthread_barrier_t barrier;
    int scan_error;
    int destroy_error;
};

static void *shadow_domain_scan_worker(void *argument)
{
    struct shadow_domain_destroy_context *context = argument;
    const struct shadow_scan_request request = {.max_pages = 8U, .max_candidates = 8U};
    struct shadow_scan_result result;

    (void)shadow_test_barrier_wait(&context->barrier);
    context->scan_error = shadow_scan_lruvec(context->engine, 102U, 0, &request, &result);
    return NULL;
}

static void *shadow_domain_destroy_worker(void *argument)
{
    struct shadow_domain_destroy_context *context = argument;

    (void)shadow_test_barrier_wait(&context->barrier);
    context->destroy_error = shadow_engine_destroy_domain(context->engine, 102U);
    return NULL;
}

static bool shadow_test_run_domain_destroy_race(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    const struct shadow_page_add_event add = {
        .event_seq = 1U, .page_id = 1500U, .memcg_id = 102U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_FILE, .page_type = RECLAIM_PAGE_FILE,
    };
    const struct shadow_page_reclaimed_event reclaim = {.event_seq = 2U, .page_id = 1500U};
    struct shadow_domain_destroy_context context = {0};
    pthread_t scan_thread;
    pthread_t destroy_thread;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    if (reclaim_engine_create(&platform.platform, NULL, NULL,
                              reclaim_simulator_executor_ops(), &executor, &engine) !=
        RECLAIM_OK || shadow_page_add(engine, &add) != RECLAIM_OK ||
        shadow_page_reclaimed(engine, &reclaim) != RECLAIM_OK) {
        reclaim_engine_destroy(engine);
        return false;
    }
    context.engine = engine;
    if (pthread_barrier_init(&context.barrier, NULL, 2U) != 0 ||
        pthread_create(&scan_thread, NULL, shadow_domain_scan_worker, &context) != 0 ||
        pthread_create(&destroy_thread, NULL, shadow_domain_destroy_worker, &context) != 0) {
        reclaim_engine_destroy(engine);
        return false;
    }
    (void)pthread_join(scan_thread, NULL);
    (void)pthread_join(destroy_thread, NULL);
    pthread_barrier_destroy(&context.barrier);
    if ((context.scan_error != RECLAIM_OK && context.scan_error != RECLAIM_ERR_DOMAIN_NOT_FOUND) ||
        (context.destroy_error != RECLAIM_OK &&
         context.destroy_error != RECLAIM_ERR_DOMAIN_NOT_FOUND) ||
        shadow_engine_validate(engine, NULL) != RECLAIM_OK) {
        reclaim_engine_destroy(engine);
        return false;
    }
    reclaim_engine_destroy(engine);
    return reclaim_platform_userspace_live_allocations(&platform) == 0U;
}

static bool test_shadow_lru_deterministic_interleavings(void)
{
    unsigned int round;

    for (round = 0U; round < 100U; round++) {
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_MOVE, true));
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_MOVE, false));
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_ISOLATE, true));
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_ISOLATE, false));
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_PUTBACK, true));
        TEST_ASSERT(shadow_test_run_scan_interleave(SHADOW_INTERLEAVE_PUTBACK, false));
        TEST_ASSERT(shadow_test_run_reclaim_race(false));
        TEST_ASSERT(shadow_test_run_reclaim_race(true));
        TEST_ASSERT(shadow_test_run_domain_destroy_race());
        TEST_ASSERT(test_shadow_lru_reverse_move_concurrency());
    }
    return true;
}
// #lzx--------------------------- Shadow 确定性交错并发测试结束 ---------------------------

// #lzx--------------------------- Shadow LRU 反向迁移并发测试 ---------------------------
struct shadow_move_worker {
    struct reclaim_engine *engine;
    uint64_t page_id;
    bool starts_left;
    pthread_barrier_t *start_barrier;
};

static void *shadow_reverse_move_worker(void *context)
{
    struct shadow_move_worker *worker = context;
    unsigned int index;
    int barrier_result;

    for (index = 0U; index < 1000U; index++) {
        if (index == 0U && worker->start_barrier != NULL) {
            barrier_result = pthread_barrier_wait(worker->start_barrier);
            if (barrier_result != 0 && barrier_result != PTHREAD_BARRIER_SERIAL_THREAD) {
                return (void *)1;
            }
        }
        bool left_to_right = (index % 2U == 0U) == worker->starts_left;
        struct shadow_page_move_event event = {
            .page_id = worker->page_id,
            .source_memcg_id = left_to_right ? 10U : 11U,
            .source_nid = left_to_right ? 0 : 1,
            .source_state = SHADOW_PAGE_ON_LRU,
            .source_lru = SHADOW_LRU_INACTIVE_ANON,
            .target_memcg_id = left_to_right ? 11U : 10U,
            .target_nid = left_to_right ? 1 : 0,
            .target_lru = SHADOW_LRU_INACTIVE_ANON,
            .reason = SHADOW_MOVE_MEMCG_AND_NUMA,
            .page_type = RECLAIM_PAGE_ANON,
        };

        if (shadow_page_move(worker->engine, &event) != RECLAIM_OK) {
            return (void *)1;
        }
    }
    return NULL;
}

static bool test_shadow_lru_reverse_move_concurrency(void)
{
    struct reclaim_userspace_platform platform;
    struct reclaim_simulator_executor executor;
    struct reclaim_engine *engine = NULL;
    struct shadow_page_add_event left = {
        .page_id = 400U, .memcg_id = 10U, .nid = 0,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_page_add_event right = {
        .page_id = 401U, .memcg_id = 11U, .nid = 1,
        .lru = SHADOW_LRU_INACTIVE_ANON, .page_type = RECLAIM_PAGE_ANON,
    };
    struct shadow_move_worker first = {.page_id = 400U, .starts_left = true};
    struct shadow_move_worker second = {.page_id = 401U, .starts_left = false};
    pthread_barrier_t start_barrier;
    pthread_t first_thread;
    pthread_t second_thread;
    void *first_result = NULL;
    void *second_result = NULL;

    reclaim_platform_userspace_init(&platform);
    reclaim_simulator_executor_init(&executor);
    TEST_ASSERT(reclaim_engine_create(&platform.platform, NULL, NULL,
                                      reclaim_simulator_executor_ops(), &executor,
                                      &engine) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &left) == RECLAIM_OK);
    TEST_ASSERT(shadow_page_add(engine, &right) == RECLAIM_OK);
    TEST_ASSERT(pthread_barrier_init(&start_barrier, NULL, 2U) == 0);
    first.engine = engine;
    second.engine = engine;
    first.start_barrier = &start_barrier;
    second.start_barrier = &start_barrier;
    TEST_ASSERT(pthread_create(&first_thread, NULL, shadow_reverse_move_worker, &first) == 0);
    TEST_ASSERT(pthread_create(&second_thread, NULL, shadow_reverse_move_worker, &second) == 0);
    TEST_ASSERT(pthread_join(first_thread, &first_result) == 0);
    TEST_ASSERT(pthread_join(second_thread, &second_result) == 0);
    TEST_ASSERT(first_result == NULL);
    TEST_ASSERT(second_result == NULL);
    pthread_barrier_destroy(&start_barrier);
    TEST_ASSERT(shadow_engine_validate(engine, NULL) == RECLAIM_OK);
    reclaim_engine_destroy(engine);
    TEST_ASSERT_EQ_U64(0U, reclaim_platform_userspace_live_allocations(&platform));
    return true;
}
// #lzx--------------------------- Shadow LRU 反向迁移并发测试结束 ---------------------------

// #lzx--------------------------- Shadow LRU 测试注册 ---------------------------
void register_test_shadow_lru(void)
{
    reclaim_test_register("shadow lru sparse nodes and lifecycle",
                          test_shadow_lru_sparse_nodes_and_lifecycle);
    reclaim_test_register("shadow lru event order and reclaim", // #lzx
                          test_shadow_lru_event_order_and_reclaim); // #lzx
    reclaim_test_register("shadow lru stale duplicate do not create targets", // #lzx
                          test_shadow_lru_stale_duplicate_do_not_create_targets); // #lzx
    reclaim_test_register("shadow lru move and node scan", // #lzx
                          test_shadow_lru_move_and_node_scan); // #lzx
    reclaim_test_register("shadow lru candidates revalidate", // #lzx
                          test_shadow_lru_candidates_revalidate); // #lzx
    reclaim_test_register("shadow lru candidate collection matrix", // #lzx
                          test_shadow_lru_candidate_collection_matrix); // #lzx
    reclaim_test_register("shadow lru candidate invalidation matrix", // #lzx
                          test_shadow_lru_candidate_invalidation_matrix); // #lzx
    reclaim_test_register("shadow lru validator bidirectional faults", // #lzx
                          test_shadow_lru_validator_bidirectional_faults); // #lzx
    reclaim_test_register("shadow lru deterministic interleavings", // #lzx
                          test_shadow_lru_deterministic_interleavings); // #lzx
    reclaim_test_register("shadow lru reverse move concurrency", // #lzx
                          test_shadow_lru_reverse_move_concurrency); // #lzx
}
// #lzx--------------------------- Shadow LRU 测试注册结束 ---------------------------
