// #lzx: per-memcg-per-node Shadow LRU implementation

#include "myself_kswapd/shadow_lru.h"
#include "myself_kswapd/executor.h"
#include "../test_support/test.h"

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

// #lzx--------------------------- Shadow LRU 反向迁移并发测试 ---------------------------
struct shadow_move_worker {
    struct reclaim_engine *engine;
    uint64_t page_id;
    bool starts_left;
};

static void *shadow_reverse_move_worker(void *context)
{
    struct shadow_move_worker *worker = context;
    unsigned int index;

    for (index = 0U; index < 1000U; index++) {
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
    first.engine = engine;
    second.engine = engine;
    TEST_ASSERT(pthread_create(&first_thread, NULL, shadow_reverse_move_worker, &first) == 0);
    TEST_ASSERT(pthread_create(&second_thread, NULL, shadow_reverse_move_worker, &second) == 0);
    TEST_ASSERT(pthread_join(first_thread, &first_result) == 0);
    TEST_ASSERT(pthread_join(second_thread, &second_result) == 0);
    TEST_ASSERT(first_result == NULL);
    TEST_ASSERT(second_result == NULL);
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
    reclaim_test_register("shadow lru reverse move concurrency", // #lzx
                          test_shadow_lru_reverse_move_concurrency); // #lzx
}
// #lzx--------------------------- Shadow LRU 测试注册结束 ---------------------------
