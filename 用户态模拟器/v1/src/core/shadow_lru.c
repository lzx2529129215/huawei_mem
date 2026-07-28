// #lzx: per-memcg-per-node Shadow LRU implementation

#include "internal.h"
#include "myself_kswapd/validator.h"

#include <limits.h>
#include <stddef.h>

// #lzx--------------------------- Shadow LRU 基础工具 ---------------------------
static size_t shadow_hash(uint64_t value, size_t buckets)
{
    return (size_t)((value * UINT64_C(11400714819323198485)) % buckets);
}

static bool shadow_valid_nid(int nid)
{
    return nid >= 0;
}

static bool shadow_valid_lru(enum shadow_lru_type lru)
{
    return lru >= SHADOW_LRU_INACTIVE_ANON && lru < SHADOW_LRU_NR;
}

static bool shadow_valid_page_type(enum reclaim_page_type page_type)
{
    return page_type == RECLAIM_PAGE_ANON || page_type == RECLAIM_PAGE_FILE;
}

static enum shadow_lru_origin shadow_origin_from_lru(enum shadow_lru_type lru)
{
    return shadow_valid_lru(lru) ? (enum shadow_lru_origin)lru :
           SHADOW_LRU_ORIGIN_UNKNOWN;
}

static bool shadow_lru_matches_page_type(enum shadow_lru_type lru,
                                         enum reclaim_page_type page_type)
{
    return (page_type == RECLAIM_PAGE_ANON &&
            (lru == SHADOW_LRU_INACTIVE_ANON || lru == SHADOW_LRU_ACTIVE_ANON)) ||
           (page_type == RECLAIM_PAGE_FILE &&
            (lru == SHADOW_LRU_INACTIVE_FILE || lru == SHADOW_LRU_ACTIVE_FILE));
}

static enum reclaim_page_type shadow_page_type_from_lru(enum shadow_lru_type lru)
{
    return lru == SHADOW_LRU_INACTIVE_ANON || lru == SHADOW_LRU_ACTIVE_ANON ?
           RECLAIM_PAGE_ANON : RECLAIM_PAGE_FILE;
}

static unsigned long shadow_page_base_pages(const struct shadow_page *page)
{
    if (page->order >= sizeof(unsigned long) * CHAR_BIT) {
        return ULONG_MAX;
    }
    return 1UL << page->order;
}

static void shadow_record_global_validation(struct reclaim_engine *engine, uint64_t flag)
{
    (void)atomic_fetch_or(&engine->shadow_validation_flags, flag);
}

static void shadow_record_validation(struct reclaim_engine *engine,
                                     struct shadow_lruvec *lruvec,
                                     uint64_t flag)
{
    shadow_record_global_validation(engine, flag);
    if (lruvec != NULL) {
        pthread_mutex_lock(&lruvec->lock);
        lruvec->validation_flags |= flag;
        pthread_mutex_unlock(&lruvec->lock);
    }
}

static uint64_t shadow_resolve_event_seq(struct reclaim_engine *engine, uint64_t requested)
{
    uint_fast64_t observed;

    if (requested == 0U) {
        return atomic_fetch_add(&engine->shadow_event_seq, 1U) + 1U;
    }
    observed = atomic_load(&engine->shadow_event_seq);
    while (observed < requested &&
           !atomic_compare_exchange_weak(&engine->shadow_event_seq, &observed, requested)) {
    }
    return requested;
}
// #lzx--------------------------- Shadow LRU 基础工具结束 ---------------------------

// #lzx--------------------------- domain 和稀疏 node table ---------------------------
static struct shadow_domain *shadow_find_domain_locked(const struct reclaim_engine *engine,
                                                        uint64_t memcg_id)
{
    struct shadow_domain *domain;
    size_t bucket = shadow_hash(memcg_id, engine->shadow_domains.bucket_count);

    for (domain = engine->shadow_domains.buckets[bucket]; domain != NULL;
         domain = domain->hash_next) {
        if (domain->memcg_id == memcg_id) {
            return domain;
        }
    }
    return NULL;
}

static void shadow_domain_get(struct shadow_domain *domain)
{
    (void)atomic_fetch_add(&domain->refcount, 1U);
}

static void shadow_lruvec_destroy(struct reclaim_engine *engine, struct shadow_lruvec *lruvec)
{
    if (lruvec == NULL) {
        return;
    }
    pthread_mutex_destroy(&lruvec->lock);
    reclaim_free(engine, lruvec);
}

static void shadow_domain_destroy(struct reclaim_engine *engine, struct shadow_domain *domain)
{
    size_t index;

    for (index = 0U; index < domain->node_table.bucket_count; index++) {
        struct shadow_lruvec *lruvec = domain->node_table.buckets[index];
        while (lruvec != NULL) {
            struct shadow_lruvec *next = lruvec->hash_next;
            shadow_lruvec_destroy(engine, lruvec);
            lruvec = next;
        }
    }
    reclaim_free(engine, domain->node_table.buckets);
    pthread_mutex_destroy(&domain->node_table_lock);
    reclaim_free(engine, domain);
}

static void shadow_domain_put(struct reclaim_engine *engine, struct shadow_domain *domain)
{
    if (domain != NULL && atomic_fetch_sub(&domain->refcount, 1U) == 1U) {
        shadow_domain_destroy(engine, domain);
    }
}

static struct shadow_domain *shadow_domain_alloc(struct reclaim_engine *engine, uint64_t memcg_id)
{
    struct shadow_domain *domain = reclaim_calloc(engine, 1U, sizeof(*domain));

    if (domain == NULL) {
        return NULL;
    }
    domain->memcg_id = memcg_id;
    atomic_init(&domain->refcount, 1U);
    domain->node_table.bucket_count = 16U;
    domain->node_table.buckets = reclaim_calloc(engine, domain->node_table.bucket_count,
                                                sizeof(*domain->node_table.buckets));
    if (domain->node_table.buckets == NULL ||
        pthread_mutex_init(&domain->node_table_lock, NULL) != 0) {
        reclaim_free(engine, domain->node_table.buckets);
        reclaim_free(engine, domain);
        return NULL;
    }
    return domain;
}

static int shadow_domain_get_by_id(struct reclaim_engine *engine,
                                   uint64_t memcg_id,
                                   struct shadow_domain **out_domain)
{
    struct shadow_domain *domain;

    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    domain = shadow_find_domain_locked(engine, memcg_id);
    if (domain != NULL && !domain->dying) {
        shadow_domain_get(domain);
    } else {
        domain = NULL;
    }
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    if (domain == NULL) {
        return RECLAIM_ERR_DOMAIN_NOT_FOUND;
    }
    *out_domain = domain;
    return RECLAIM_OK;
}

static int shadow_domain_get_or_create(struct reclaim_engine *engine,
                                       uint64_t memcg_id,
                                       struct shadow_domain **out_domain)
{
    struct shadow_domain *domain;
    size_t bucket;

    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    domain = shadow_find_domain_locked(engine, memcg_id);
    if (domain == NULL) {
        domain = shadow_domain_alloc(engine, memcg_id);
        if (domain != NULL) {
            bucket = shadow_hash(memcg_id, engine->shadow_domains.bucket_count);
            domain->hash_next = engine->shadow_domains.buckets[bucket];
            engine->shadow_domains.buckets[bucket] = domain;
        }
    }
    if (domain != NULL && !domain->dying) {
        shadow_domain_get(domain);
    } else {
        domain = NULL;
    }
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    if (domain == NULL) {
        return RECLAIM_ERR_NO_MEMORY;
    }
    *out_domain = domain;
    return RECLAIM_OK;
}

static struct shadow_lruvec *shadow_find_lruvec_locked(const struct shadow_domain *domain,
                                                        int nid)
{
    struct shadow_lruvec *lruvec;
    size_t bucket = shadow_hash((uint64_t)(unsigned int)nid, domain->node_table.bucket_count);

    for (lruvec = domain->node_table.buckets[bucket]; lruvec != NULL; lruvec = lruvec->hash_next) {
        if (lruvec->nid == nid) {
            return lruvec;
        }
    }
    return NULL;
}

static struct shadow_lruvec *shadow_lruvec_alloc(struct reclaim_engine *engine, int nid)
{
    struct shadow_lruvec *lruvec = reclaim_calloc(engine, 1U, sizeof(*lruvec));
    size_t index;

    if (lruvec == NULL || pthread_mutex_init(&lruvec->lock, NULL) != 0) {
        reclaim_free(engine, lruvec);
        return NULL;
    }
    lruvec->nid = nid;
    for (index = 0U; index < SHADOW_LRU_NR; index++) {
        reclaim_list_init(&lruvec->lists[index]);
    }
    reclaim_list_init(&lruvec->isolated);
    return lruvec;
}

static int shadow_lruvec_get(struct reclaim_engine *engine,
                             struct shadow_domain *domain,
                             int nid,
                             bool create,
                             struct shadow_lruvec **out_lruvec)
{
    struct shadow_lruvec *lruvec;
    size_t bucket;

    if (!shadow_valid_nid(nid)) {
        shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_NID);
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    pthread_mutex_lock(&domain->node_table_lock);
    lruvec = shadow_find_lruvec_locked(domain, nid);
    if (lruvec == NULL && create) {
        lruvec = shadow_lruvec_alloc(engine, nid);
        if (lruvec != NULL) {
            bucket = shadow_hash((uint64_t)(unsigned int)nid, domain->node_table.bucket_count);
            lruvec->hash_next = domain->node_table.buckets[bucket];
            domain->node_table.buckets[bucket] = lruvec;
        }
    }
    pthread_mutex_unlock(&domain->node_table_lock);
    if (lruvec == NULL) {
        return RECLAIM_ERR_DOMAIN_NOT_FOUND;
    }
    *out_lruvec = lruvec;
    return RECLAIM_OK;
}
// #lzx--------------------------- domain 和稀疏 node table 结束 ---------------------------

// #lzx--------------------------- 页面表、引用和链操作 ---------------------------
static struct shadow_page *shadow_find_page_locked(const struct reclaim_engine *engine,
                                                   uint64_t page_id)
{
    struct shadow_page *page;
    size_t bucket = shadow_hash(page_id, engine->shadow_pages.bucket_count);

    for (page = engine->shadow_pages.buckets[bucket]; page != NULL; page = page->hash_next) {
        if (page->page_id == page_id) {
            return page;
        }
    }
    return NULL;
}

static void shadow_page_get(struct shadow_page *page)
{
    (void)atomic_fetch_add(&page->refcount, 1U);
}

static void shadow_page_put(struct reclaim_engine *engine, struct shadow_page *page)
{
    if (page != NULL && atomic_fetch_sub(&page->refcount, 1U) == 1U) {
        if (!page->dying || page->state != SHADOW_PAGE_DETACHED ||
            page->container != NULL || page->list_node.list != NULL) {
            shadow_record_global_validation(engine, SHADOW_VALIDATION_REFCOUNT_ERROR);
        }
        pthread_mutex_destroy(&page->lock);
        reclaim_free(engine, page);
    }
}

static struct shadow_page *shadow_page_alloc(struct reclaim_engine *engine, uint64_t page_id)
{
    struct shadow_page *page = reclaim_calloc(engine, 1U, sizeof(*page));

    if (page == NULL || pthread_mutex_init(&page->lock, NULL) != 0) {
        reclaim_free(engine, page);
        return NULL;
    }
    page->page_id = page_id;
    atomic_init(&page->refcount, 2U);
    atomic_init(&page->last_event_seq, 0U);
    page->state = SHADOW_PAGE_DETACHED;
    page->isolated_from = SHADOW_LRU_ORIGIN_UNKNOWN;
    page->putback_hint = SHADOW_LRU_NR;
    return page;
}

static int shadow_page_lookup_get(struct reclaim_engine *engine,
                                  uint64_t page_id,
                                  struct shadow_page **out_page)
{
    struct shadow_page *page;

    pthread_mutex_lock(&engine->shadow_page_table_lock);
    page = shadow_find_page_locked(engine, page_id);
    if (page != NULL && !page->dying) {
        shadow_page_get(page);
    } else {
        page = NULL;
    }
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    if (page == NULL) {
        return RECLAIM_ERR_PAGE_NOT_FOUND;
    }
    *out_page = page;
    return RECLAIM_OK;
}

static int shadow_page_create_and_insert(struct reclaim_engine *engine,
                                         uint64_t page_id,
                                         struct shadow_page **out_page)
{
    struct shadow_page *page;
    size_t bucket;

    page = shadow_page_alloc(engine, page_id);
    if (page == NULL) {
        return RECLAIM_ERR_NO_MEMORY;
    }
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    if (shadow_find_page_locked(engine, page_id) != NULL) {
        pthread_mutex_unlock(&engine->shadow_page_table_lock);
        page->dying = true;
        shadow_page_put(engine, page);
        shadow_page_put(engine, page);
        return RECLAIM_ERR_PAGE_ALREADY_EXISTS;
    }
    bucket = shadow_hash(page_id, engine->shadow_pages.bucket_count);
    page->hash_next = engine->shadow_pages.buckets[bucket];
    engine->shadow_pages.buckets[bucket] = page;
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    *out_page = page;
    return RECLAIM_OK;
}

static void shadow_page_remove_locked(struct reclaim_engine *engine, struct shadow_page *page)
{
    struct shadow_page **cursor;
    size_t bucket = shadow_hash(page->page_id, engine->shadow_pages.bucket_count);

    for (cursor = &engine->shadow_pages.buckets[bucket]; *cursor != NULL;
         cursor = &(*cursor)->hash_next) {
        if (*cursor == page) {
            *cursor = page->hash_next;
            page->hash_next = NULL;
            return;
        }
    }
}

static void shadow_attach_lru_locked(struct shadow_page *page,
                                     struct shadow_lruvec *lruvec,
                                     enum shadow_lru_type lru)
{
    unsigned long pages = shadow_page_base_pages(page);

    page->list_node.owner = page;
    reclaim_list_push_back(&lruvec->lists[lru], &page->list_node);
    lruvec->nr_pages[lru] += pages;
    page->container = lruvec;
    page->nid = lruvec->nid;
    page->state = SHADOW_PAGE_ON_LRU;
    page->current_lru = lru;
    page->isolated_from = SHADOW_LRU_ORIGIN_UNKNOWN;
    page->putback_hint = SHADOW_LRU_NR;
}

static void shadow_attach_isolated_locked(struct shadow_page *page,
                                          struct shadow_lruvec *lruvec,
                                          enum shadow_lru_origin origin,
                                          enum shadow_lru_type hint)
{
    page->list_node.owner = page;
    reclaim_list_push_back(&lruvec->isolated, &page->list_node);
    lruvec->nr_isolated++;
    page->container = lruvec;
    page->nid = lruvec->nid;
    page->state = SHADOW_PAGE_ISOLATED;
    page->current_lru = SHADOW_LRU_NR;
    page->isolated_from = origin;
    page->putback_hint = hint;
}

static void shadow_detach_locked(struct shadow_page *page)
{
    struct shadow_lruvec *lruvec = page->container;
    unsigned long pages = shadow_page_base_pages(page);

    if (page->state == SHADOW_PAGE_ON_LRU && shadow_valid_lru(page->current_lru)) {
        reclaim_list_remove(&lruvec->lists[page->current_lru], &page->list_node);
        if (lruvec->nr_pages[page->current_lru] >= pages) {
            lruvec->nr_pages[page->current_lru] -= pages;
        }
    } else if (page->state == SHADOW_PAGE_ISOLATED) {
        reclaim_list_remove(&lruvec->isolated, &page->list_node);
        if (lruvec->nr_isolated > 0U) {
            lruvec->nr_isolated--;
        }
    }
    page->container = NULL;
    page->state = SHADOW_PAGE_DETACHED;
    page->current_lru = SHADOW_LRU_NR;
}

static int shadow_lruvec_order(const struct shadow_domain *left_domain,
                               const struct shadow_lruvec *left,
                               const struct shadow_domain *right_domain,
                               const struct shadow_lruvec *right)
{
    if (left_domain->memcg_id != right_domain->memcg_id) {
        return left_domain->memcg_id < right_domain->memcg_id ? -1 : 1;
    }
    if (left->nid != right->nid) {
        return left->nid < right->nid ? -1 : 1;
    }
    return 0;
}

static void shadow_lock_lruvec_pair(const struct shadow_domain *left_domain,
                                    struct shadow_lruvec *left,
                                    const struct shadow_domain *right_domain,
                                    struct shadow_lruvec *right)
{
    int order = shadow_lruvec_order(left_domain, left, right_domain, right);

    if (left == right) {
        pthread_mutex_lock(&left->lock);
    } else if (order < 0) {
        pthread_mutex_lock(&left->lock);
        pthread_mutex_lock(&right->lock);
    } else {
        pthread_mutex_lock(&right->lock);
        pthread_mutex_lock(&left->lock);
    }
}

static void shadow_unlock_lruvec_pair(const struct shadow_domain *left_domain,
                                      struct shadow_lruvec *left,
                                      const struct shadow_domain *right_domain,
                                      struct shadow_lruvec *right)
{
    int order = shadow_lruvec_order(left_domain, left, right_domain, right);

    if (left == right) {
        pthread_mutex_unlock(&left->lock);
    } else if (order < 0) {
        pthread_mutex_unlock(&right->lock);
        pthread_mutex_unlock(&left->lock);
    } else {
        pthread_mutex_unlock(&left->lock);
        pthread_mutex_unlock(&right->lock);
    }
}
// #lzx--------------------------- 页面表、引用和链操作结束 ---------------------------

// #lzx--------------------------- 事件门控和迁移 ---------------------------
enum shadow_event_action {
    SHADOW_EVENT_APPLY = 0,
    SHADOW_EVENT_DUPLICATE,
    SHADOW_EVENT_STALE,
};

static enum shadow_event_action shadow_event_gate_locked(struct reclaim_engine *engine,
                                                          struct shadow_page *page,
                                                          uint64_t event_seq)
{
    uint64_t last_event_seq = atomic_load(&page->last_event_seq);

    if (event_seq == last_event_seq) {
        shadow_record_validation(engine, page->container, SHADOW_VALIDATION_DUPLICATE_EVENT);
        return SHADOW_EVENT_DUPLICATE;
    }
    if (event_seq < last_event_seq) {
        shadow_record_validation(engine, page->container, SHADOW_VALIDATION_STALE_EVENT);
        return SHADOW_EVENT_STALE;
    }
    return SHADOW_EVENT_APPLY;
}

static void shadow_event_commit_locked(struct shadow_page *page, uint64_t event_seq)
{
    atomic_store(&page->last_event_seq, event_seq);
}

static struct shadow_domain *shadow_move_page_locked(struct reclaim_engine *engine,
                                                     struct shadow_page *page,
                                                     struct shadow_domain *target_domain,
                                                     struct shadow_lruvec *target_lruvec,
                                                     bool target_isolated,
                                                     enum shadow_lru_type target_lru,
                                                     enum shadow_lru_origin origin,
                                                     enum shadow_lru_type hint)
{
    struct shadow_domain *old_domain = page->domain;
    struct shadow_lruvec *old_lruvec = page->container;

    (void)engine;

    if (old_lruvec != NULL) {
        shadow_lock_lruvec_pair(old_domain, old_lruvec, target_domain, target_lruvec);
        shadow_detach_locked(page);
    } else {
        pthread_mutex_lock(&target_lruvec->lock);
    }
    if (old_domain != target_domain) {
        page->domain = target_domain;
        page->memcg_id = target_domain->memcg_id;
    }
    if (target_isolated) {
        shadow_attach_isolated_locked(page, target_lruvec, origin, hint);
    } else {
        shadow_attach_lru_locked(page, target_lruvec, target_lru);
    }
    if (old_lruvec != NULL) {
        shadow_unlock_lruvec_pair(old_domain, old_lruvec, target_domain, target_lruvec);
    } else {
        pthread_mutex_unlock(&target_lruvec->lock);
    }
    return old_domain == target_domain ? target_domain : old_domain;
}

static void shadow_update_static_metadata_locked(struct shadow_page *page,
                                                 enum reclaim_page_type page_type,
                                                 bool provisional)
{
    if (shadow_valid_page_type(page_type)) {
        page->page_type = page_type;
    }
    if (!provisional) {
        page->provisional = false;
    }
}

static void shadow_fill_static_metadata_locked(struct shadow_page *page,
                                               enum reclaim_page_type page_type,
                                               uint32_t order)
{
    if (page->provisional) {
        page->page_type = page_type;
        page->order = order;
        page->provisional = false;
    }
}

static void shadow_update_static_metadata(struct shadow_page *page,
                                          enum reclaim_page_type page_type,
                                          bool provisional,
                                          bool update_order,
                                          uint32_t order)
{
    struct shadow_lruvec *lruvec = page->container;

    if (lruvec != NULL) {
        pthread_mutex_lock(&lruvec->lock);
    }
    shadow_update_static_metadata_locked(page, page_type, provisional);
    if (update_order) {
        page->order = order;
    }
    if (lruvec != NULL) {
        pthread_mutex_unlock(&lruvec->lock);
    }
}

static void shadow_fill_static_metadata(struct shadow_page *page,
                                        enum reclaim_page_type page_type,
                                        uint32_t order)
{
    struct shadow_lruvec *lruvec = page->container;

    if (lruvec != NULL) {
        pthread_mutex_lock(&lruvec->lock);
    }
    shadow_fill_static_metadata_locked(page, page_type, order);
    if (lruvec != NULL) {
        pthread_mutex_unlock(&lruvec->lock);
    }
}
// #lzx--------------------------- 事件门控和迁移结束 ---------------------------

// #lzx--------------------------- Shadow 生命周期公开实现 ---------------------------
int shadow_engine_create_domain(struct reclaim_engine *engine, uint64_t memcg_id)
{
    struct shadow_domain *domain;
    size_t bucket;

    if (engine == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    if (shadow_find_domain_locked(engine, memcg_id) != NULL) {
        pthread_mutex_unlock(&engine->shadow_domain_table_lock);
        return RECLAIM_ERR_DOMAIN_ALREADY_EXISTS;
    }
    domain = shadow_domain_alloc(engine, memcg_id);
    if (domain == NULL) {
        pthread_mutex_unlock(&engine->shadow_domain_table_lock);
        return RECLAIM_ERR_NO_MEMORY;
    }
    bucket = shadow_hash(memcg_id, engine->shadow_domains.bucket_count);
    domain->hash_next = engine->shadow_domains.buckets[bucket];
    engine->shadow_domains.buckets[bucket] = domain;
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    return RECLAIM_OK;
}

int shadow_engine_destroy_domain(struct reclaim_engine *engine, uint64_t memcg_id)
{
    struct shadow_domain **cursor;
    struct shadow_domain *domain;
    size_t bucket;
    size_t index;

    if (engine == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    bucket = shadow_hash(memcg_id, engine->shadow_domains.bucket_count);
    for (cursor = &engine->shadow_domains.buckets[bucket]; *cursor != NULL;
         cursor = &(*cursor)->hash_next) {
        if ((*cursor)->memcg_id == memcg_id) {
            break;
        }
    }
    domain = *cursor;
    if (domain == NULL) {
        pthread_mutex_unlock(&engine->shadow_domain_table_lock);
        return RECLAIM_ERR_DOMAIN_NOT_FOUND;
    }
    pthread_mutex_lock(&domain->node_table_lock);
    for (index = 0U; index < domain->node_table.bucket_count; index++) {
        struct shadow_lruvec *lruvec;
        for (lruvec = domain->node_table.buckets[index]; lruvec != NULL;
             lruvec = lruvec->hash_next) {
            if (!reclaim_list_empty(&lruvec->isolated) ||
                lruvec->nr_pages[SHADOW_LRU_INACTIVE_ANON] != 0U ||
                lruvec->nr_pages[SHADOW_LRU_ACTIVE_ANON] != 0U ||
                lruvec->nr_pages[SHADOW_LRU_INACTIVE_FILE] != 0U ||
                lruvec->nr_pages[SHADOW_LRU_ACTIVE_FILE] != 0U) {
                pthread_mutex_unlock(&domain->node_table_lock);
                pthread_mutex_unlock(&engine->shadow_domain_table_lock);
                return RECLAIM_ERR_DOMAIN_NOT_EMPTY;
            }
        }
    }
    pthread_mutex_unlock(&domain->node_table_lock);
    *cursor = domain->hash_next;
    domain->hash_next = NULL;
    domain->dying = true;
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    shadow_domain_put(engine, domain);
    return RECLAIM_OK;
}

int shadow_page_add(struct reclaim_engine *engine, const struct shadow_page_add_event *event)
{
    struct shadow_page *page;
    struct shadow_domain *domain = NULL;
    struct shadow_lruvec *lruvec;
    enum shadow_event_action action;
    uint64_t seq;
    int error;

    if (engine == NULL || event == NULL || !shadow_valid_nid(event->nid) ||
        !shadow_valid_lru(event->lru) || !shadow_valid_page_type(event->page_type) ||
        !shadow_lru_matches_page_type(event->lru, event->page_type) ||
        event->order >= sizeof(unsigned long) * CHAR_BIT) {
        if (engine != NULL) {
            shadow_record_global_validation(engine, !shadow_valid_nid(event == NULL ? -1 : event->nid) ?
                                            SHADOW_VALIDATION_INVALID_NID :
                                            SHADOW_VALIDATION_INVALID_LRU_TYPE);
        }
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    seq = shadow_resolve_event_seq(engine, event->event_seq);
    error = shadow_page_lookup_get(engine, event->page_id, &page);
    if (error == RECLAIM_ERR_PAGE_NOT_FOUND) {
        error = shadow_page_create_and_insert(engine, event->page_id, &page);
        if (error != RECLAIM_OK) {
            return error;
        }
        error = shadow_domain_get_or_create(engine, event->memcg_id, &domain);
        if (error == RECLAIM_OK) {
            error = shadow_lruvec_get(engine, domain, event->nid, true, &lruvec);
        }
        if (error != RECLAIM_OK) {
            pthread_mutex_lock(&engine->shadow_page_table_lock);
            shadow_page_remove_locked(engine, page);
            page->dying = true;
            pthread_mutex_unlock(&engine->shadow_page_table_lock);
            shadow_page_put(engine, page);
            shadow_page_put(engine, page);
            if (domain != NULL) {
                shadow_domain_put(engine, domain);
            }
            return error;
        }
        pthread_mutex_lock(&page->lock);
        atomic_store(&page->last_event_seq, seq);
        page->page_type = event->page_type;
        page->order = event->order;
        page->domain = domain;
        page->memcg_id = event->memcg_id;
        page->provisional = false;
        pthread_mutex_lock(&lruvec->lock);
        shadow_attach_lru_locked(page, lruvec, event->lru);
        pthread_mutex_unlock(&lruvec->lock);
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    if (error != RECLAIM_OK) {
        return error;
    }
    pthread_mutex_lock(&page->lock);
    action = shadow_event_gate_locked(engine, page, seq);
    if (action == SHADOW_EVENT_APPLY) {
        shadow_event_commit_locked(page, seq);
        shadow_update_static_metadata(page, event->page_type, false, true, event->order);
    } else if (action == SHADOW_EVENT_STALE) {
        shadow_fill_static_metadata(page, event->page_type, event->order);
    }
    pthread_mutex_unlock(&page->lock);
    shadow_page_put(engine, page);
    return RECLAIM_OK;
}

int shadow_page_isolate(struct reclaim_engine *engine,
                         const struct shadow_page_isolate_event *event)
{
    struct shadow_page *page;
    struct shadow_domain *target_domain = NULL;
    struct shadow_lruvec *target_lruvec;
    struct shadow_domain *release_domain = NULL;
    enum shadow_event_action action;
    uint64_t seq;
    int error;

    if (engine == NULL || event == NULL || !shadow_valid_nid(event->nid) ||
        !shadow_valid_lru(event->source_lru) || !shadow_valid_page_type(event->page_type) ||
        !shadow_lru_matches_page_type(event->source_lru, event->page_type)) {
        if (engine != NULL) {
            shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_LRU_TYPE);
        }
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    seq = shadow_resolve_event_seq(engine, event->event_seq);
    error = shadow_page_lookup_get(engine, event->page_id, &page);
    if (error == RECLAIM_ERR_PAGE_NOT_FOUND) {
        error = shadow_page_create_and_insert(engine, event->page_id, &page);
        if (error != RECLAIM_OK) return error;
        shadow_record_global_validation(engine, SHADOW_VALIDATION_ISOLATE_UNKNOWN_PAGE);
        error = shadow_domain_get_or_create(engine, event->memcg_id, &target_domain);
        if (error == RECLAIM_OK) {
            error = shadow_lruvec_get(engine, target_domain, event->nid, true, &target_lruvec);
        }
        if (error != RECLAIM_OK) goto isolate_new_error;
        pthread_mutex_lock(&page->lock);
        atomic_store(&page->last_event_seq, seq);
        page->page_type = event->page_type;
        page->domain = target_domain;
        page->memcg_id = event->memcg_id;
        page->provisional = true;
        pthread_mutex_lock(&target_lruvec->lock);
        shadow_attach_isolated_locked(page, target_lruvec, shadow_origin_from_lru(event->source_lru),
                                      event->source_lru);
        target_lruvec->nr_isolate_events++;
        pthread_mutex_unlock(&target_lruvec->lock);
        page->isolate_seq = seq;
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    if (error != RECLAIM_OK) return error;
    pthread_mutex_lock(&page->lock);
    action = shadow_event_gate_locked(engine, page, seq);
    if (action != SHADOW_EVENT_APPLY) {
        if (action == SHADOW_EVENT_STALE) {
            shadow_fill_static_metadata(page, event->page_type, page->order);
        }
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    error = shadow_domain_get_or_create(engine, event->memcg_id, &target_domain);
    if (error == RECLAIM_OK) {
        error = shadow_lruvec_get(engine, target_domain, event->nid, true, &target_lruvec);
    }
    if (error != RECLAIM_OK) {
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        if (target_domain != NULL) shadow_domain_put(engine, target_domain);
        return error;
    }
    shadow_event_commit_locked(page, seq);
    if (page->state == SHADOW_PAGE_ISOLATED && page->container == target_lruvec &&
            page->memcg_id == event->memcg_id) {
        shadow_record_validation(engine, target_lruvec, SHADOW_VALIDATION_DUPLICATE_ISOLATE);
    } else {
        release_domain = shadow_move_page_locked(engine, page, target_domain, target_lruvec, true,
                                                  SHADOW_LRU_NR,
                                                  shadow_origin_from_lru(event->source_lru),
                                                  event->source_lru);
        pthread_mutex_lock(&target_lruvec->lock);
        target_lruvec->nr_isolate_events++;
        pthread_mutex_unlock(&target_lruvec->lock);
    }
    shadow_update_static_metadata(page, event->page_type, false, false, page->order);
    page->isolate_seq = seq;
    pthread_mutex_unlock(&page->lock);
    if (release_domain == NULL || release_domain == target_domain) {
        shadow_domain_put(engine, target_domain);
    } else {
        shadow_domain_put(engine, release_domain);
    }
    shadow_page_put(engine, page);
    return RECLAIM_OK;

isolate_new_error:
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    shadow_page_remove_locked(engine, page);
    page->dying = true;
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    shadow_page_put(engine, page);
    shadow_page_put(engine, page);
    if (target_domain != NULL) shadow_domain_put(engine, target_domain);
    return error;
}

int shadow_page_putback(struct reclaim_engine *engine,
                         const struct shadow_page_putback_event *event)
{
    struct shadow_page *page;
    struct shadow_domain *target_domain = NULL;
    struct shadow_lruvec *target_lruvec;
    struct shadow_domain *release_domain = NULL;
    enum shadow_event_action action;
    uint64_t seq;
    int error;

    if (engine == NULL || event == NULL || !shadow_valid_nid(event->target_nid) ||
        !shadow_valid_lru(event->target_lru)) {
        if (engine != NULL) shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_LRU_TYPE);
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    seq = shadow_resolve_event_seq(engine, event->event_seq);
    error = shadow_page_lookup_get(engine, event->page_id, &page);
    if (error == RECLAIM_ERR_PAGE_NOT_FOUND) {
        error = shadow_page_create_and_insert(engine, event->page_id, &page);
        if (error != RECLAIM_OK) return error;
        shadow_record_global_validation(engine, SHADOW_VALIDATION_PUTBACK_UNKNOWN_PAGE);
        error = shadow_domain_get_or_create(engine, event->target_memcg_id, &target_domain);
        if (error == RECLAIM_OK) error = shadow_lruvec_get(engine, target_domain,
                                                            event->target_nid, true,
                                                            &target_lruvec);
        if (error != RECLAIM_OK) goto putback_new_error;
        pthread_mutex_lock(&page->lock);
        atomic_store(&page->last_event_seq, seq);
        page->domain = target_domain;
        page->memcg_id = event->target_memcg_id;
        page->nid = event->target_nid;
        page->page_type = shadow_page_type_from_lru(event->target_lru);
        page->provisional = true;
        pthread_mutex_lock(&target_lruvec->lock);
        shadow_attach_lru_locked(page, target_lruvec, event->target_lru);
        target_lruvec->nr_putback++;
        pthread_mutex_unlock(&target_lruvec->lock);
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    if (error != RECLAIM_OK) return error;
    pthread_mutex_lock(&page->lock);
    action = shadow_event_gate_locked(engine, page, seq);
    if (action != SHADOW_EVENT_APPLY) {
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    error = shadow_domain_get_or_create(engine, event->target_memcg_id, &target_domain);
    if (error == RECLAIM_OK) {
        error = shadow_lruvec_get(engine, target_domain, event->target_nid, true, &target_lruvec);
    }
    if (error != RECLAIM_OK) {
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        if (target_domain != NULL) shadow_domain_put(engine, target_domain);
        return error;
    }
    shadow_event_commit_locked(page, seq);
    if (page->state != SHADOW_PAGE_ISOLATED) {
        shadow_record_validation(engine, page->container,
                                 SHADOW_VALIDATION_PUTBACK_WITHOUT_ISOLATE);
    } else if (page->putback_hint != event->target_lru) {
        shadow_record_validation(engine, page->container,
                                 SHADOW_VALIDATION_PUTBACK_HINT_MISMATCH);
    }
    release_domain = shadow_move_page_locked(engine, page, target_domain, target_lruvec,
                                              false, event->target_lru,
                                              SHADOW_LRU_ORIGIN_UNKNOWN, SHADOW_LRU_NR);
    pthread_mutex_lock(&target_lruvec->lock);
    target_lruvec->nr_putback++;
    pthread_mutex_unlock(&target_lruvec->lock);
    pthread_mutex_unlock(&page->lock);
    if (release_domain == NULL || release_domain == target_domain) {
        shadow_domain_put(engine, target_domain);
    } else {
        shadow_domain_put(engine, release_domain);
    }
    shadow_page_put(engine, page);
    return RECLAIM_OK;

putback_new_error:
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    shadow_page_remove_locked(engine, page);
    page->dying = true;
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    shadow_page_put(engine, page);
    shadow_page_put(engine, page);
    if (target_domain != NULL) shadow_domain_put(engine, target_domain);
    return error;
}

int shadow_page_reclaimed(struct reclaim_engine *engine,
                          const struct shadow_page_reclaimed_event *event)
{
    struct shadow_page *page;
    struct shadow_domain *old_domain;
    struct shadow_lruvec *lruvec;
    enum shadow_event_action action;
    uint64_t seq;

    if (engine == NULL || event == NULL) return RECLAIM_ERR_INVALID_ARGUMENT;
    seq = shadow_resolve_event_seq(engine, event->event_seq);
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    page = shadow_find_page_locked(engine, event->page_id);
    if (page == NULL || page->dying) {
        pthread_mutex_unlock(&engine->shadow_page_table_lock);
        shadow_record_global_validation(engine, SHADOW_VALIDATION_RECLAIM_UNKNOWN_PAGE);
        return RECLAIM_OK;
    }
    shadow_page_get(page);
    pthread_mutex_lock(&page->lock);
    action = shadow_event_gate_locked(engine, page, seq);
    if (action != SHADOW_EVENT_APPLY) {
        pthread_mutex_unlock(&page->lock);
        pthread_mutex_unlock(&engine->shadow_page_table_lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    shadow_event_commit_locked(page, seq);
    shadow_page_remove_locked(engine, page);
    page->dying = true;
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    old_domain = page->domain;
    lruvec = page->container;
    if (page->state != SHADOW_PAGE_ISOLATED) {
        shadow_record_validation(engine, lruvec, SHADOW_VALIDATION_RECLAIM_WITHOUT_ISOLATE);
    }
    if (lruvec != NULL) {
        pthread_mutex_lock(&lruvec->lock);
        shadow_detach_locked(page);
        lruvec->nr_reclaimed++;
        pthread_mutex_unlock(&lruvec->lock);
    }
    page->domain = NULL;
    pthread_mutex_unlock(&page->lock);
    shadow_domain_put(engine, old_domain);
    shadow_page_put(engine, page);
    shadow_page_put(engine, page);
    return RECLAIM_OK;
}

int shadow_page_move(struct reclaim_engine *engine, const struct shadow_page_move_event *event)
{
    struct shadow_page *page;
    struct shadow_domain *target_domain = NULL;
    struct shadow_lruvec *target_lruvec;
    struct shadow_domain *release_domain = NULL;
    struct shadow_lruvec *source_lruvec = NULL;
    enum shadow_event_action action;
    bool target_isolated;
    uint64_t seq;
    int error;

    if (engine == NULL || event == NULL || !shadow_valid_nid(event->source_nid) ||
        !shadow_valid_nid(event->target_nid) || !shadow_valid_lru(event->source_lru) ||
        !shadow_valid_lru(event->target_lru) || !shadow_valid_page_type(event->page_type) ||
        !shadow_lru_matches_page_type(event->target_lru, event->page_type) ||
        event->source_state > SHADOW_PAGE_ISOLATED ||
        event->reason > SHADOW_MOVE_MEMCG_AND_NUMA) {
        if (engine != NULL) shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_LRU_TYPE);
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    seq = shadow_resolve_event_seq(engine, event->event_seq);
    error = shadow_page_lookup_get(engine, event->page_id, &page);
    if (error == RECLAIM_ERR_PAGE_NOT_FOUND) {
        error = shadow_page_create_and_insert(engine, event->page_id, &page);
        if (error != RECLAIM_OK) return error;
        shadow_record_global_validation(engine, SHADOW_VALIDATION_MOVE_UNKNOWN_PAGE);
        error = shadow_domain_get_or_create(engine, event->target_memcg_id, &target_domain);
        if (error == RECLAIM_OK) error = shadow_lruvec_get(engine, target_domain,
                                                            event->target_nid, true,
                                                            &target_lruvec);
        if (error != RECLAIM_OK) goto move_new_error;
        target_isolated = event->source_state == SHADOW_PAGE_ISOLATED;
        pthread_mutex_lock(&page->lock);
        atomic_store(&page->last_event_seq, seq);
        page->domain = target_domain;
        page->memcg_id = event->target_memcg_id;
        page->page_type = event->page_type;
        page->provisional = true;
        pthread_mutex_lock(&target_lruvec->lock);
        if (target_isolated) {
            shadow_attach_isolated_locked(page, target_lruvec, SHADOW_LRU_ORIGIN_UNKNOWN,
                                          event->target_lru);
        } else {
            shadow_attach_lru_locked(page, target_lruvec, event->target_lru);
        }
        target_lruvec->nr_move_in++;
        pthread_mutex_unlock(&target_lruvec->lock);
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    if (error != RECLAIM_OK) return error;
    pthread_mutex_lock(&page->lock);
    action = shadow_event_gate_locked(engine, page, seq);
    if (action != SHADOW_EVENT_APPLY) {
        if (action == SHADOW_EVENT_STALE) {
            shadow_fill_static_metadata(page, event->page_type, page->order);
        }
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        return RECLAIM_OK;
    }
    error = shadow_domain_get_or_create(engine, event->target_memcg_id, &target_domain);
    if (error == RECLAIM_OK) {
        error = shadow_lruvec_get(engine, target_domain, event->target_nid, true, &target_lruvec);
    }
    if (error != RECLAIM_OK) {
        pthread_mutex_unlock(&page->lock);
        shadow_page_put(engine, page);
        if (target_domain != NULL) shadow_domain_put(engine, target_domain);
        return error;
    }
    shadow_event_commit_locked(page, seq);
    if (page->memcg_id != event->source_memcg_id || page->nid != event->source_nid ||
            page->state != event->source_state ||
            (page->state == SHADOW_PAGE_ON_LRU && page->current_lru != event->source_lru)) {
        shadow_record_validation(engine, page->container, SHADOW_VALIDATION_MOVE_SOURCE_MISMATCH);
    }
    target_isolated = page->state == SHADOW_PAGE_ISOLATED;
    source_lruvec = page->container;
    release_domain = shadow_move_page_locked(engine, page, target_domain, target_lruvec,
                                              target_isolated, event->target_lru,
                                              target_isolated ? page->isolated_from :
                                              SHADOW_LRU_ORIGIN_UNKNOWN,
                                              event->target_lru);
    if (source_lruvec != NULL) {
        pthread_mutex_lock(&source_lruvec->lock);
        source_lruvec->nr_move_out++;
        pthread_mutex_unlock(&source_lruvec->lock);
    }
    pthread_mutex_lock(&target_lruvec->lock);
    target_lruvec->nr_move_in++;
    pthread_mutex_unlock(&target_lruvec->lock);
    shadow_update_static_metadata(page, event->page_type, false, false, page->order);
    pthread_mutex_unlock(&page->lock);
    if (release_domain == NULL || release_domain == target_domain) {
        shadow_domain_put(engine, target_domain);
    } else {
        shadow_domain_put(engine, release_domain);
    }
    shadow_page_put(engine, page);
    return RECLAIM_OK;

move_new_error:
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    shadow_page_remove_locked(engine, page);
    page->dying = true;
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    shadow_page_put(engine, page);
    shadow_page_put(engine, page);
    if (target_domain != NULL) shadow_domain_put(engine, target_domain);
    return error;
}
// #lzx--------------------------- Shadow 生命周期公开实现结束 ---------------------------

// #lzx--------------------------- Shadow 扫描与查询实现 ---------------------------
static void shadow_scan_locked(const struct shadow_lruvec *lruvec,
                               const struct shadow_scan_request *request,
                               struct shadow_scan_result *result)
{
    static const enum shadow_lru_type order[] = {
        SHADOW_LRU_INACTIVE_ANON,
        SHADOW_LRU_INACTIVE_FILE,
        SHADOW_LRU_ACTIVE_ANON,
        SHADOW_LRU_ACTIVE_FILE,
    };
    size_t index;

    for (index = 0U; index < sizeof(order) / sizeof(order[0]); index++) {
        enum shadow_lru_type lru = order[index];
        const struct reclaim_list *list = &lruvec->lists[lru];
        const struct reclaim_list_node *node;

        for (node = list->head.next; node != &list->head; node = node->next) {
            const struct shadow_page *page = node->owner;
            unsigned long pages;

            if (page == NULL || page->state != SHADOW_PAGE_ON_LRU ||
                page->current_lru != lru || page->container != lruvec) {
                result->nr_skipped++;
                continue;
            }
            pages = shadow_page_base_pages(page);
            if (request->max_pages != 0U && result->nr_pages_scanned + pages >
                request->max_pages) {
                result->nr_skipped++;
                continue;
            }
            result->nr_pages_scanned += pages;
            if (page->page_type == RECLAIM_PAGE_ANON) {
                result->nr_anon_scanned += pages;
            } else {
                result->nr_file_scanned += pages;
            }
            if (lru == SHADOW_LRU_ACTIVE_ANON || lru == SHADOW_LRU_ACTIVE_FILE) {
                result->nr_protected += pages;
            } else if (request->max_candidates == 0U ||
                       result->nr_candidates_selected < request->max_candidates) {
                result->nr_candidates_selected++;
            } else {
                result->nr_skipped++;
            }
        }
    }
}

int shadow_page_get_info(struct reclaim_engine *engine,
                         uint64_t page_id,
                         struct shadow_page_info *info)
{
    struct shadow_page *page;
    int error;

    if (engine == NULL || info == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    error = shadow_page_lookup_get(engine, page_id, &page);
    if (error != RECLAIM_OK) {
        return error;
    }
    pthread_mutex_lock(&page->lock);
    *info = (struct shadow_page_info){
        .page_id = page->page_id,
        .memcg_id = page->memcg_id,
        .nid = page->nid,
        .state = page->state,
        .current_lru = page->current_lru,
        .isolated_from = page->isolated_from,
        .putback_hint = page->putback_hint,
        .last_event_seq = atomic_load(&page->last_event_seq),
        .isolate_seq = page->isolate_seq,
        .page_type = page->page_type,
        .provisional = page->provisional,
        .dying = page->dying,
    };
    pthread_mutex_unlock(&page->lock);
    shadow_page_put(engine, page);
    return RECLAIM_OK;
}

int shadow_lruvec_get_stats(struct reclaim_engine *engine,
                            uint64_t memcg_id,
                            int nid,
                            struct shadow_lruvec_stats *stats)
{
    struct shadow_domain *domain;
    struct shadow_lruvec *lruvec;
    int error;

    if (engine == NULL || stats == NULL || !shadow_valid_nid(nid)) {
        if (engine != NULL && !shadow_valid_nid(nid)) {
            shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_NID);
        }
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    error = shadow_domain_get_by_id(engine, memcg_id, &domain);
    if (error != RECLAIM_OK) {
        return error;
    }
    error = shadow_lruvec_get(engine, domain, nid, false, &lruvec);
    if (error == RECLAIM_OK) {
        pthread_mutex_lock(&lruvec->lock);
        *stats = (struct shadow_lruvec_stats){
            .nr_pages = {lruvec->nr_pages[0], lruvec->nr_pages[1],
                         lruvec->nr_pages[2], lruvec->nr_pages[3]},
            .nr_isolated = lruvec->nr_isolated,
            .nr_isolate_events = lruvec->nr_isolate_events,
            .nr_putback = lruvec->nr_putback,
            .nr_reclaimed = lruvec->nr_reclaimed,
            .nr_move_in = lruvec->nr_move_in,
            .nr_move_out = lruvec->nr_move_out,
            .validation_flags = lruvec->validation_flags,
        };
        pthread_mutex_unlock(&lruvec->lock);
    }
    shadow_domain_put(engine, domain);
    return error;
}

int shadow_scan_lruvec(struct reclaim_engine *engine,
                       uint64_t memcg_id,
                       int nid,
                       const struct shadow_scan_request *request,
                       struct shadow_scan_result *result)
{
    struct shadow_domain *domain;
    struct shadow_lruvec *lruvec;
    int error;

    if (engine == NULL || request == NULL || result == NULL || !shadow_valid_nid(nid)) {
        if (engine != NULL && !shadow_valid_nid(nid)) {
            shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_NID);
        }
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    *result = (struct shadow_scan_result){0};
    error = shadow_domain_get_by_id(engine, memcg_id, &domain);
    if (error != RECLAIM_OK) {
        return error;
    }
    error = shadow_lruvec_get(engine, domain, nid, false, &lruvec);
    if (error == RECLAIM_OK) {
        pthread_mutex_lock(&lruvec->lock);
        shadow_scan_locked(lruvec, request, result);
        pthread_mutex_unlock(&lruvec->lock);
    }
    shadow_domain_put(engine, domain);
    return error;
}

int shadow_scan_node(struct reclaim_engine *engine,
                     int nid,
                     const struct shadow_node_scan_request *request,
                     struct shadow_node_scan_result *result)
{
    struct shadow_domain **domains;
    size_t capacity = 0U;
    size_t count = 0U;
    size_t bucket;
    size_t index;

    if (engine == NULL || request == NULL || result == NULL || !shadow_valid_nid(nid)) {
        if (engine != NULL && !shadow_valid_nid(nid)) {
            shadow_record_global_validation(engine, SHADOW_VALIDATION_INVALID_NID);
        }
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    *result = (struct shadow_node_scan_result){0};
    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    for (bucket = 0U; bucket < engine->shadow_domains.bucket_count; bucket++) {
        struct shadow_domain *domain;
        for (domain = engine->shadow_domains.buckets[bucket]; domain != NULL;
             domain = domain->hash_next) {
            capacity++;
        }
    }
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    if (capacity == 0U) {
        return RECLAIM_OK;
    }
    domains = reclaim_calloc(engine, capacity, sizeof(*domains));
    if (domains == NULL) {
        return RECLAIM_ERR_NO_MEMORY;
    }
    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    for (bucket = 0U; bucket < engine->shadow_domains.bucket_count; bucket++) {
        struct shadow_domain *domain;
        for (domain = engine->shadow_domains.buckets[bucket]; domain != NULL;
             domain = domain->hash_next) {
            if (!domain->dying && count < capacity) {
                shadow_domain_get(domain);
                domains[count++] = domain;
            }
        }
    }
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    for (index = 0U; index < count; index++) {
        struct shadow_lruvec *lruvec;
        struct shadow_scan_request per_domain = {
            .max_pages = request->max_pages_per_domain,
            .max_candidates = request->max_candidates_per_domain,
        };
        struct shadow_scan_result partial = {0};

        result->nr_domains_considered++;
        if (shadow_lruvec_get(engine, domains[index], nid, false, &lruvec) == RECLAIM_OK) {
            pthread_mutex_lock(&lruvec->lock);
            shadow_scan_locked(lruvec, &per_domain, &partial);
            pthread_mutex_unlock(&lruvec->lock);
            result->nr_domains_scanned++;
            result->nr_pages_scanned += partial.nr_pages_scanned;
            result->nr_candidates_selected += partial.nr_candidates_selected;
            result->nr_anon_scanned += partial.nr_anon_scanned;
            result->nr_file_scanned += partial.nr_file_scanned;
            result->nr_protected += partial.nr_protected;
            result->nr_skipped += partial.nr_skipped;
        }
        shadow_domain_put(engine, domains[index]);
    }
    reclaim_free(engine, domains);
    return RECLAIM_OK;
}

// #lzx--------------------------- Shadow 候选收集与重验证 ---------------------------
static void shadow_collect_candidates_locked(const struct shadow_lruvec *lruvec,
                                             const struct shadow_candidate_request *request,
                                             struct shadow_candidate *candidates,
                                             size_t capacity,
                                             struct shadow_candidate_result *result)
{
    size_t type;

    for (type = 0U; type < SHADOW_LRU_NR; type++) {
        const struct reclaim_list *list = &lruvec->lists[type];
        const struct reclaim_list_node *node;
        for (node = list->head.next; node != &list->head; node = node->next) {
            const struct shadow_page *page = node->owner;
            unsigned long pages;

            if (page == NULL || page->state != SHADOW_PAGE_ON_LRU ||
                page->container != lruvec || page->current_lru != (enum shadow_lru_type)type) {
                continue;
            }
            result->nr_total_eligible++;
            pages = shadow_page_base_pages(page);
            if (request->max_pages != 0U && result->nr_pages_collected + pages >
                request->max_pages) {
                result->nr_truncated++;
                continue;
            }
            if ((request->max_candidates != 0U && result->nr_candidates >=
                 request->max_candidates) || result->nr_candidates >= capacity) {
                result->nr_truncated++;
                continue;
            }
            candidates[result->nr_candidates++] = (struct shadow_candidate){
                .page_id = page->page_id,
                .memcg_id = page->memcg_id,
                .nid = page->nid,
                .expected_state = page->state,
                .expected_lru = page->current_lru,
                .event_seq = atomic_load(&page->last_event_seq),
            };
            result->nr_pages_collected += pages;
        }
    }
    result->truncated = result->nr_truncated != 0U;
}

int shadow_collect_lruvec_candidates(struct reclaim_engine *engine,
                                     uint64_t memcg_id,
                                     int nid,
                                     const struct shadow_candidate_request *request,
                                     struct shadow_candidate *candidates,
                                     size_t capacity,
                                     struct shadow_candidate_result *result)
{
    struct shadow_domain *domain;
    struct shadow_lruvec *lruvec;
    int error;

    if (engine == NULL || request == NULL || result == NULL || !shadow_valid_nid(nid) ||
        (capacity != 0U && candidates == NULL)) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    *result = (struct shadow_candidate_result){0};
    error = shadow_domain_get_by_id(engine, memcg_id, &domain);
    if (error != RECLAIM_OK) {
        return error;
    }
    error = shadow_lruvec_get(engine, domain, nid, false, &lruvec);
    if (error == RECLAIM_OK) {
        pthread_mutex_lock(&lruvec->lock);
        shadow_collect_candidates_locked(lruvec, request, candidates, capacity, result);
        pthread_mutex_unlock(&lruvec->lock);
    }
    shadow_domain_put(engine, domain);
    return error;
}

int shadow_candidate_revalidate(struct reclaim_engine *engine,
                                const struct shadow_candidate *candidate,
                                struct shadow_candidate_validation *result)
{
    struct shadow_page *page;

    if (engine == NULL || candidate == NULL || result == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    *result = (struct shadow_candidate_validation){.status = SHADOW_CANDIDATE_PAGE_MISSING};
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    page = shadow_find_page_locked(engine, candidate->page_id);
    if (page == NULL) {
        pthread_mutex_unlock(&engine->shadow_page_table_lock);
        return RECLAIM_OK;
    }
    if (page->dying) {
        pthread_mutex_unlock(&engine->shadow_page_table_lock);
        result->status = SHADOW_CANDIDATE_PAGE_DYING;
        return RECLAIM_OK;
    }
    shadow_page_get(page);
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    pthread_mutex_lock(&page->lock);
    if (page->memcg_id != candidate->memcg_id || page->nid != candidate->nid) {
        result->status = SHADOW_CANDIDATE_LOCATION_CHANGED;
    } else if (page->state != candidate->expected_state || page->state != SHADOW_PAGE_ON_LRU) {
        result->status = SHADOW_CANDIDATE_STATE_CHANGED;
    } else if (page->current_lru != candidate->expected_lru) {
        result->status = SHADOW_CANDIDATE_LRU_CHANGED;
    } else if (atomic_load(&page->last_event_seq) != candidate->event_seq) {
        result->status = SHADOW_CANDIDATE_EVENT_SEQ_CHANGED;
    } else {
        result->status = SHADOW_CANDIDATE_VALID;
    }
    pthread_mutex_unlock(&page->lock);
    shadow_page_put(engine, page);
    return RECLAIM_OK;
}
// #lzx--------------------------- Shadow 候选收集与重验证结束 ---------------------------
// #lzx--------------------------- Shadow 扫描与查询实现结束 ---------------------------

// #lzx--------------------------- Shadow 一致性校验与引擎生命周期 ---------------------------
static int shadow_validation_fail(struct reclaim_validation_report *report,
                                  const struct reclaim_engine *engine,
                                  uint64_t page_id,
                                  uint64_t memcg_id,
                                  const char *invariant,
                                  uint64_t expected,
                                  uint64_t observed)
{
    shadow_record_global_validation((struct reclaim_engine *)engine,
                                    SHADOW_VALIDATION_CHAIN_STATE_MISMATCH);
    if (report != NULL) {
        *report = (struct reclaim_validation_report){
            .event_seq = atomic_load(&engine->shadow_event_seq),
            .page_id = page_id,
            .cgroup_id = memcg_id,
            .invariant = invariant,
            .expected = expected,
            .observed = observed,
        };
    }
    return RECLAIM_ERR_VALIDATION;
}

static bool shadow_page_is_indexed_quiescent(const struct reclaim_engine *engine,
                                              const struct shadow_page *needle)
{
    const struct shadow_page *page;
    size_t bucket = shadow_hash(needle->page_id, engine->shadow_pages.bucket_count);

    for (page = engine->shadow_pages.buckets[bucket]; page != NULL; page = page->hash_next) {
        if (page == needle) {
            return true;
        }
    }
    return false;
}

static int shadow_validate_lruvec(const struct reclaim_engine *engine,
                                  const struct shadow_domain *domain,
                                  const struct shadow_lruvec *lruvec,
                                  struct reclaim_validation_report *report)
{
    enum shadow_lru_type type;

    for (type = SHADOW_LRU_INACTIVE_ANON; type < SHADOW_LRU_NR; type++) {
        const struct reclaim_list *list = &lruvec->lists[type];
        const struct reclaim_list_node *node;
        unsigned long pages = 0U;
        uint64_t folios = 0U;

        for (node = list->head.next; node != &list->head; node = node->next) {
            const struct shadow_page *page = node->owner;
            if (page == NULL || !shadow_page_is_indexed_quiescent(engine, page) ||
                node->list != list || page->state != SHADOW_PAGE_ON_LRU ||
                page->container != lruvec || page->current_lru != type ||
                page->domain != domain || page->memcg_id != domain->memcg_id ||
                page->nid != lruvec->nid || !shadow_lru_matches_page_type(type, page->page_type)) {
                return shadow_validation_fail(report, engine, page == NULL ? 0U : page->page_id,
                                              domain->memcg_id, "shadow lru linkage", 1U, 0U);
            }
            folios++;
            pages += shadow_page_base_pages(page);
        }
        if (list->nr_folios != folios || lruvec->nr_pages[type] != pages) {
            return shadow_validation_fail(report, engine, 0U, domain->memcg_id,
                                          "shadow lru counters", pages,
                                          lruvec->nr_pages[type]);
        }
    }
    {
        const struct reclaim_list_node *node;
        uint64_t isolated = 0U;
        for (node = lruvec->isolated.head.next; node != &lruvec->isolated.head; node = node->next) {
            const struct shadow_page *page = node->owner;
            if (page == NULL || !shadow_page_is_indexed_quiescent(engine, page) ||
                node->list != &lruvec->isolated ||
                page->state != SHADOW_PAGE_ISOLATED || page->container != lruvec ||
                page->domain != domain || page->memcg_id != domain->memcg_id ||
                page->nid != lruvec->nid || !shadow_valid_lru(page->putback_hint)) {
                return shadow_validation_fail(report, engine, page == NULL ? 0U : page->page_id,
                                              domain->memcg_id, "shadow isolated linkage", 1U, 0U);
            }
            isolated++;
        }
        if (lruvec->isolated.nr_folios != isolated || lruvec->nr_isolated != isolated) {
            return shadow_validation_fail(report, engine, 0U, domain->memcg_id,
                                          "shadow isolated counters", isolated,
                                          lruvec->nr_isolated);
        }
    }
    return RECLAIM_OK;
}

int shadow_engine_validate(struct reclaim_engine *engine,
                           struct reclaim_validation_report *report)
{
    size_t bucket;

    if (engine == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    pthread_mutex_lock(&engine->shadow_domain_table_lock);
    for (bucket = 0U; bucket < engine->shadow_domains.bucket_count; bucket++) {
        struct shadow_domain *domain;
        for (domain = engine->shadow_domains.buckets[bucket]; domain != NULL;
             domain = domain->hash_next) {
            size_t node_bucket;
            if (domain->dying || domain->memcg_id == UINT64_MAX) {
                pthread_mutex_unlock(&engine->shadow_domain_table_lock);
                return shadow_validation_fail(report, engine, 0U, domain->memcg_id,
                                              "shadow domain table entry", 0U, 1U);
            }
            pthread_mutex_lock(&domain->node_table_lock);
            for (node_bucket = 0U; node_bucket < domain->node_table.bucket_count; node_bucket++) {
                struct shadow_lruvec *lruvec;
                for (lruvec = domain->node_table.buckets[node_bucket]; lruvec != NULL;
                     lruvec = lruvec->hash_next) {
                    int error;
                    if (!shadow_valid_nid(lruvec->nid) ||
                        shadow_hash((uint64_t)(unsigned int)lruvec->nid,
                                    domain->node_table.bucket_count) != node_bucket) {
                        pthread_mutex_unlock(&domain->node_table_lock);
                        pthread_mutex_unlock(&engine->shadow_domain_table_lock);
                        return shadow_validation_fail(report, engine, 0U, domain->memcg_id,
                                                      "shadow node key", 1U, 0U);
                    }
                    pthread_mutex_lock(&lruvec->lock);
                    error = shadow_validate_lruvec(engine, domain, lruvec, report);
                    pthread_mutex_unlock(&lruvec->lock);
                    if (error != RECLAIM_OK) {
                        pthread_mutex_unlock(&domain->node_table_lock);
                        pthread_mutex_unlock(&engine->shadow_domain_table_lock);
                        return error;
                    }
                }
            }
            pthread_mutex_unlock(&domain->node_table_lock);
        }
    }
    pthread_mutex_unlock(&engine->shadow_domain_table_lock);
    pthread_mutex_lock(&engine->shadow_page_table_lock);
    for (bucket = 0U; bucket < engine->shadow_pages.bucket_count; bucket++) {
        struct shadow_page *page;
        for (page = engine->shadow_pages.buckets[bucket]; page != NULL; page = page->hash_next) {
            if (page->dying || page->state == SHADOW_PAGE_DETACHED || page->container == NULL ||
                page->domain == NULL || page->list_node.list == NULL ||
                shadow_find_page_locked(engine, page->page_id) != page) {
                pthread_mutex_unlock(&engine->shadow_page_table_lock);
                return shadow_validation_fail(report, engine, page->page_id, page->memcg_id,
                                              "shadow page table entry", 1U, 0U);
            }
        }
    }
    pthread_mutex_unlock(&engine->shadow_page_table_lock);
    return RECLAIM_OK;
}

uint64_t shadow_engine_event_seq(const struct reclaim_engine *engine)
{
    return engine == NULL ? 0U : atomic_load(&engine->shadow_event_seq);
}

uint64_t shadow_engine_validation_flags(const struct reclaim_engine *engine)
{
    return engine == NULL ? SHADOW_VALIDATION_NONE :
           atomic_load(&engine->shadow_validation_flags);
}

int shadow_engine_state_init(struct reclaim_engine *engine)
{
    if (engine == NULL) {
        return RECLAIM_ERR_INVALID_ARGUMENT;
    }
    engine->shadow_pages.bucket_count = engine->config.page_hash_buckets;
    engine->shadow_domains.bucket_count = engine->config.domain_hash_buckets;
    engine->shadow_pages.buckets = reclaim_calloc(engine, engine->shadow_pages.bucket_count,
                                                  sizeof(*engine->shadow_pages.buckets));
    engine->shadow_domains.buckets = reclaim_calloc(engine, engine->shadow_domains.bucket_count,
                                                    sizeof(*engine->shadow_domains.buckets));
    if (engine->shadow_pages.buckets == NULL || engine->shadow_domains.buckets == NULL ||
        pthread_mutex_init(&engine->shadow_page_table_lock, NULL) != 0) {
        reclaim_free(engine, engine->shadow_pages.buckets);
        reclaim_free(engine, engine->shadow_domains.buckets);
        engine->shadow_pages.buckets = NULL;
        engine->shadow_domains.buckets = NULL;
        return RECLAIM_ERR_NO_MEMORY;
    }
    if (pthread_mutex_init(&engine->shadow_domain_table_lock, NULL) != 0) {
        pthread_mutex_destroy(&engine->shadow_page_table_lock);
        reclaim_free(engine, engine->shadow_pages.buckets);
        reclaim_free(engine, engine->shadow_domains.buckets);
        engine->shadow_pages.buckets = NULL;
        engine->shadow_domains.buckets = NULL;
        return RECLAIM_ERR_NO_MEMORY;
    }
    atomic_init(&engine->shadow_event_seq, 0U);
    atomic_init(&engine->shadow_validation_flags, SHADOW_VALIDATION_NONE);
    return RECLAIM_OK;
}

void shadow_engine_state_destroy(struct reclaim_engine *engine)
{
    size_t bucket;

    if (engine == NULL || engine->shadow_pages.buckets == NULL ||
        engine->shadow_domains.buckets == NULL) {
        return;
    }
    for (bucket = 0U; bucket < engine->shadow_pages.bucket_count; bucket++) {
        struct shadow_page *page = engine->shadow_pages.buckets[bucket];
        while (page != NULL) {
            struct shadow_page *next = page->hash_next;
            pthread_mutex_destroy(&page->lock);
            reclaim_free(engine, page);
            page = next;
        }
    }
    for (bucket = 0U; bucket < engine->shadow_domains.bucket_count; bucket++) {
        struct shadow_domain *domain = engine->shadow_domains.buckets[bucket];
        while (domain != NULL) {
            struct shadow_domain *next = domain->hash_next;
            shadow_domain_destroy(engine, domain);
            domain = next;
        }
    }
    reclaim_free(engine, engine->shadow_pages.buckets);
    reclaim_free(engine, engine->shadow_domains.buckets);
    pthread_mutex_destroy(&engine->shadow_page_table_lock);
    pthread_mutex_destroy(&engine->shadow_domain_table_lock);
    engine->shadow_pages.buckets = NULL;
    engine->shadow_domains.buckets = NULL;
}
// #lzx--------------------------- Shadow 一致性校验与引擎生命周期结束 ---------------------------
