#ifndef RECLAIM_CORE_INTERNAL_H
#define RECLAIM_CORE_INTERNAL_H

#include "myself_kswapd/engine.h"
#include "myself_kswapd/executor.h"
#include "myself_kswapd/shadow_lru.h"

#include <pthread.h>
#include <stdatomic.h>

struct reclaim_page_table {
    struct reclaim_page **buckets;
    size_t bucket_count;
};

struct reclaim_domain {
    uint64_t cgroup_id;
    struct reclaim_list inactive_anon;
    struct reclaim_list active_anon;
    struct reclaim_list inactive_file;
    struct reclaim_list active_file;
    struct reclaim_domain_config config;
    struct reclaim_domain_stats stats;
    struct reclaim_domain *hash_next;
    struct reclaim_domain *sorted_prev;
    struct reclaim_domain *sorted_next;
};

struct reclaim_domain_table {
    struct reclaim_domain **buckets;
    size_t bucket_count;
    struct reclaim_domain *sorted_head;
};

// #lzx--------------------------- Shadow LRU 内部对象 ---------------------------
struct shadow_lruvec {
    int nid;
    pthread_mutex_t lock;
    struct reclaim_list lists[SHADOW_LRU_NR];
    struct reclaim_list isolated;
    unsigned long nr_pages[SHADOW_LRU_NR];
    unsigned long nr_isolated;
    unsigned long nr_isolate_events;
    unsigned long nr_putback;
    unsigned long nr_reclaimed;
    unsigned long nr_move_in;
    unsigned long nr_move_out;
    uint64_t validation_flags;
    struct shadow_lruvec *hash_next;
};

struct shadow_node_table {
    struct shadow_lruvec **buckets;
    size_t bucket_count;
};

struct shadow_domain {
    uint64_t memcg_id;
    atomic_uint refcount;
    bool dying;
    pthread_mutex_t node_table_lock;
    struct shadow_node_table node_table;
    struct shadow_domain *hash_next;
};

struct shadow_domain_table {
    struct shadow_domain **buckets;
    size_t bucket_count;
};

struct shadow_page {
    uint64_t page_id;
    atomic_uint refcount;
    bool dying;
    pthread_mutex_t lock;
    uint64_t memcg_id;
    int nid;
    struct shadow_domain *domain;
    struct shadow_lruvec *container;
    enum shadow_page_state state;
    enum shadow_lru_type current_lru;
    enum shadow_lru_origin isolated_from;
    enum shadow_lru_type putback_hint;
    uint64_t last_event_seq;
    uint64_t isolate_seq;
    enum reclaim_page_type page_type;
    uint32_t order;
    bool provisional;
    struct reclaim_list_node list_node;
    struct shadow_page *hash_next;
};

struct shadow_page_table {
    struct shadow_page **buckets;
    size_t bucket_count;
};
// #lzx--------------------------- Shadow LRU 内部对象结束 ---------------------------

struct reclaim_engine {
    struct reclaim_platform platform;
    struct reclaim_engine_config config;
    struct reclaim_page_table pages;
    struct reclaim_domain_table domains;
    const struct reclaim_aging_ops *aging_ops;
    const struct reclaim_executor_ops *executor_ops;
    void *executor_context;
    struct reclaim_engine_stats stats;
    uint64_t event_seq;
    pthread_mutex_t shadow_page_table_lock; // #lzx
    struct shadow_page_table shadow_pages; // #lzx
    pthread_mutex_t shadow_domain_table_lock; // #lzx
    struct shadow_domain_table shadow_domains; // #lzx
    atomic_uint_fast64_t shadow_event_seq; // #lzx
    atomic_uint_fast64_t shadow_validation_flags; // #lzx
};

void *reclaim_alloc(struct reclaim_engine *engine, size_t size);
void *reclaim_calloc(struct reclaim_engine *engine, size_t count, size_t size);
void reclaim_free(struct reclaim_engine *engine, void *pointer);
size_t reclaim_page_bucket(const struct reclaim_engine *engine, uint64_t page_id);
size_t reclaim_domain_bucket(const struct reclaim_engine *engine, uint64_t cgroup_id);
struct reclaim_page *reclaim_find_page(struct reclaim_engine *engine, uint64_t page_id);
const struct reclaim_page *reclaim_find_page_const(const struct reclaim_engine *engine,
                                                   uint64_t page_id);
struct reclaim_domain *reclaim_find_domain(struct reclaim_engine *engine, uint64_t cgroup_id);
const struct reclaim_domain *reclaim_find_domain_const(const struct reclaim_engine *engine,
                                                       uint64_t cgroup_id);
struct reclaim_list *reclaim_domain_lru(struct reclaim_domain *domain,
                                        enum reclaim_lru_kind kind);
const struct reclaim_list *reclaim_domain_lru_const(const struct reclaim_domain *domain,
                                                    enum reclaim_lru_kind kind);
enum reclaim_lru_kind reclaim_initial_lru(enum reclaim_page_type type);
void reclaim_account_add(struct reclaim_engine *engine,
                         struct reclaim_domain *domain,
                         struct reclaim_page *page,
                         enum reclaim_lru_kind kind);
void reclaim_account_remove(struct reclaim_engine *engine,
                            struct reclaim_domain *domain,
                            struct reclaim_page *page,
                            enum reclaim_lru_kind kind);
int reclaim_link_page(struct reclaim_engine *engine,
                      struct reclaim_page *page,
                      struct reclaim_domain *domain,
                      enum reclaim_lru_kind kind,
                      enum reclaim_page_state state);
void reclaim_unlink_page(struct reclaim_engine *engine,
                         struct reclaim_page *page,
                         struct reclaim_domain *domain);
void reclaim_page_hash_insert(struct reclaim_engine *engine, struct reclaim_page *page);
void reclaim_page_hash_remove(struct reclaim_engine *engine, struct reclaim_page *page);
void reclaim_domain_hash_insert(struct reclaim_engine *engine, struct reclaim_domain *domain);
void reclaim_domain_hash_remove(struct reclaim_engine *engine, struct reclaim_domain *domain);
void reclaim_domain_sorted_insert(struct reclaim_engine *engine, struct reclaim_domain *domain);
void reclaim_domain_sorted_remove(struct reclaim_engine *engine, struct reclaim_domain *domain);

// #lzx--------------------------- Shadow LRU 内部接口 ---------------------------
int shadow_engine_state_init(struct reclaim_engine *engine);
void shadow_engine_state_destroy(struct reclaim_engine *engine);
// #lzx--------------------------- Shadow LRU 内部接口结束 ---------------------------

#endif
