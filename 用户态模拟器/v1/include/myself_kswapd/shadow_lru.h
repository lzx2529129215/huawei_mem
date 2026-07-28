// #lzx: per-memcg-per-node Shadow LRU implementation
#ifndef MYSELF_KSWAPD_SHADOW_LRU_H
#define MYSELF_KSWAPD_SHADOW_LRU_H

#include "myself_kswapd/engine.h"

#include <stdbool.h>
#include <stdint.h>

struct reclaim_validation_report;

// #lzx--------------------------- Shadow LRU 公开类型 ---------------------------
enum shadow_lru_type {
    SHADOW_LRU_INACTIVE_ANON = 0,
    SHADOW_LRU_ACTIVE_ANON,
    SHADOW_LRU_INACTIVE_FILE,
    SHADOW_LRU_ACTIVE_FILE,
    SHADOW_LRU_NR,
};

enum shadow_lru_origin {
    SHADOW_LRU_ORIGIN_INACTIVE_ANON = 0,
    SHADOW_LRU_ORIGIN_ACTIVE_ANON,
    SHADOW_LRU_ORIGIN_INACTIVE_FILE,
    SHADOW_LRU_ORIGIN_ACTIVE_FILE,
    SHADOW_LRU_ORIGIN_UNKNOWN,
};

enum shadow_page_state {
    SHADOW_PAGE_DETACHED = 0,
    SHADOW_PAGE_ON_LRU,
    SHADOW_PAGE_ISOLATED,
};

enum shadow_move_reason {
    SHADOW_MOVE_NUMA = 0,
    SHADOW_MOVE_MEMCG,
    SHADOW_MOVE_MEMCG_AND_NUMA,
};

enum shadow_validation_flag {
    SHADOW_VALIDATION_NONE = 0,
    SHADOW_VALIDATION_DUPLICATE_EVENT = UINT64_C(1) << 0,
    SHADOW_VALIDATION_STALE_EVENT = UINT64_C(1) << 1,
    SHADOW_VALIDATION_ISOLATE_UNKNOWN_PAGE = UINT64_C(1) << 2,
    SHADOW_VALIDATION_DUPLICATE_ISOLATE = UINT64_C(1) << 3,
    SHADOW_VALIDATION_PUTBACK_UNKNOWN_PAGE = UINT64_C(1) << 4,
    SHADOW_VALIDATION_PUTBACK_WITHOUT_ISOLATE = UINT64_C(1) << 5,
    SHADOW_VALIDATION_PUTBACK_HINT_MISMATCH = UINT64_C(1) << 6,
    SHADOW_VALIDATION_RECLAIM_UNKNOWN_PAGE = UINT64_C(1) << 7,
    SHADOW_VALIDATION_RECLAIM_WITHOUT_ISOLATE = UINT64_C(1) << 8,
    SHADOW_VALIDATION_MOVE_UNKNOWN_PAGE = UINT64_C(1) << 9,
    SHADOW_VALIDATION_MOVE_SOURCE_MISMATCH = UINT64_C(1) << 10,
    SHADOW_VALIDATION_INVALID_NID = UINT64_C(1) << 11,
    SHADOW_VALIDATION_INVALID_LRU_TYPE = UINT64_C(1) << 12,
    SHADOW_VALIDATION_CHAIN_STATE_MISMATCH = UINT64_C(1) << 13,
    SHADOW_VALIDATION_REFCOUNT_ERROR = UINT64_C(1) << 14,
};

struct shadow_page_add_event {
    uint64_t event_seq;
    uint64_t page_id;
    uint64_t memcg_id;
    int nid;
    enum shadow_lru_type lru;
    enum reclaim_page_type page_type;
    uint32_t order;
};

struct shadow_page_isolate_event {
    uint64_t event_seq;
    uint64_t page_id;
    uint64_t memcg_id;
    int nid;
    enum shadow_lru_type source_lru;
    enum reclaim_page_type page_type;
};

struct shadow_page_putback_event {
    uint64_t event_seq;
    uint64_t page_id;
    uint64_t target_memcg_id;
    int target_nid;
    enum shadow_lru_type target_lru;
};

struct shadow_page_reclaimed_event {
    uint64_t event_seq;
    uint64_t page_id;
};

struct shadow_page_move_event {
    uint64_t event_seq;
    uint64_t page_id;
    uint64_t source_memcg_id;
    int source_nid;
    enum shadow_page_state source_state;
    enum shadow_lru_type source_lru;
    uint64_t target_memcg_id;
    int target_nid;
    enum shadow_lru_type target_lru;
    enum shadow_move_reason reason;
    enum reclaim_page_type page_type;
};

struct shadow_page_info {
    uint64_t page_id;
    uint64_t memcg_id;
    int nid;
    enum shadow_page_state state;
    enum shadow_lru_type current_lru;
    enum shadow_lru_origin isolated_from;
    enum shadow_lru_type putback_hint;
    uint64_t last_event_seq;
    uint64_t isolate_seq;
    enum reclaim_page_type page_type;
    bool provisional;
    bool dying;
};

struct shadow_lruvec_stats {
    unsigned long nr_pages[SHADOW_LRU_NR];
    unsigned long nr_isolated;
    unsigned long nr_isolate_events;
    unsigned long nr_putback;
    unsigned long nr_reclaimed;
    unsigned long nr_move_in;
    unsigned long nr_move_out;
    uint64_t validation_flags;
};

struct shadow_scan_request {
    unsigned long max_pages;
    unsigned long max_candidates;
};

struct shadow_scan_result {
    unsigned long nr_pages_scanned;
    unsigned long nr_candidates_selected;
    unsigned long nr_anon_scanned;
    unsigned long nr_file_scanned;
    unsigned long nr_protected;
    unsigned long nr_skipped;
};

struct shadow_node_scan_request {
    unsigned long max_pages_per_domain;
    unsigned long max_candidates_per_domain;
};

struct shadow_node_scan_result {
    unsigned long nr_domains_considered;
    unsigned long nr_domains_scanned;
    unsigned long nr_pages_scanned;
    unsigned long nr_candidates_selected;
    unsigned long nr_anon_scanned;
    unsigned long nr_file_scanned;
    unsigned long nr_protected;
    unsigned long nr_skipped;
};

// #lzx--------------------------- Shadow 候选快照类型 ---------------------------
enum shadow_candidate_status {
    SHADOW_CANDIDATE_VALID = 0,
    SHADOW_CANDIDATE_PAGE_MISSING,
    SHADOW_CANDIDATE_PAGE_DYING,
    SHADOW_CANDIDATE_LOCATION_CHANGED,
    SHADOW_CANDIDATE_STATE_CHANGED,
    SHADOW_CANDIDATE_LRU_CHANGED,
    SHADOW_CANDIDATE_EVENT_SEQ_CHANGED,
};

struct shadow_candidate {
    uint64_t page_id;
    uint64_t memcg_id;
    int nid;
    enum shadow_page_state expected_state;
    enum shadow_lru_type expected_lru;
    uint64_t event_seq;
};

struct shadow_candidate_request {
    unsigned long max_pages;
    size_t max_candidates;
};

struct shadow_candidate_result {
    size_t nr_total_eligible;
    size_t nr_candidates;
    size_t nr_truncated;
    unsigned long nr_pages_collected;
    bool truncated;
};

struct shadow_candidate_validation {
    enum shadow_candidate_status status;
};
// #lzx--------------------------- Shadow 候选快照类型结束 ---------------------------
// #lzx--------------------------- Shadow LRU 公开类型结束 ---------------------------

// #lzx--------------------------- Shadow LRU 公开接口 ---------------------------
int shadow_engine_create_domain(struct reclaim_engine *engine, uint64_t memcg_id);
int shadow_engine_destroy_domain(struct reclaim_engine *engine, uint64_t memcg_id);
int shadow_page_add(struct reclaim_engine *engine, const struct shadow_page_add_event *event);
int shadow_page_isolate(struct reclaim_engine *engine,
                         const struct shadow_page_isolate_event *event);
int shadow_page_putback(struct reclaim_engine *engine,
                         const struct shadow_page_putback_event *event);
int shadow_page_reclaimed(struct reclaim_engine *engine,
                          const struct shadow_page_reclaimed_event *event);
int shadow_page_move(struct reclaim_engine *engine, const struct shadow_page_move_event *event);
int shadow_page_get_info(struct reclaim_engine *engine,
                         uint64_t page_id,
                         struct shadow_page_info *info);
int shadow_lruvec_get_stats(struct reclaim_engine *engine,
                            uint64_t memcg_id,
                            int nid,
                            struct shadow_lruvec_stats *stats);
int shadow_scan_lruvec(struct reclaim_engine *engine,
                       uint64_t memcg_id,
                       int nid,
                       const struct shadow_scan_request *request,
                       struct shadow_scan_result *result);
int shadow_scan_node(struct reclaim_engine *engine,
                     int nid,
                     const struct shadow_node_scan_request *request,
                     struct shadow_node_scan_result *result);
int shadow_collect_lruvec_candidates(struct reclaim_engine *engine,
                                     uint64_t memcg_id,
                                     int nid,
                                     const struct shadow_candidate_request *request,
                                     struct shadow_candidate *candidates,
                                     size_t capacity,
                                     struct shadow_candidate_result *result);
int shadow_candidate_revalidate(struct reclaim_engine *engine,
                                const struct shadow_candidate *candidate,
                                struct shadow_candidate_validation *result);
/*
 * #lzx: 仅可在没有并发 Shadow 事件、扫描、候选收集、domain destroy 或 engine destroy
 * 的静止点调用；该接口不会在持有 lruvec.lock 时获取 page.lock。
 */
int shadow_engine_validate(struct reclaim_engine *engine,
                           struct reclaim_validation_report *report);
uint64_t shadow_engine_event_seq(const struct reclaim_engine *engine);
uint64_t shadow_engine_validation_flags(const struct reclaim_engine *engine);
// #lzx--------------------------- Shadow LRU 公开接口结束 ---------------------------

#endif
