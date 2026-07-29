#include "myself_kswapd/kernel_snapshot_store.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#define KERNEL_SNAPSHOT_BUCKETS 64U

struct kernel_snapshot_history {
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_snapshot_history *next;
};

struct kernel_snapshot_store_entry {
    struct kernel_lruvec_key key;
    struct kernel_lruvec_snapshot latest;
    bool has_latest;
    struct kernel_snapshot_history *history;
    struct kernel_snapshot_store_entry *next;
};

static bool key_equal(const struct kernel_lruvec_key *left,
                      const struct kernel_lruvec_key *right)
{
    return left->mode == right->mode && left->memcg_id == right->memcg_id &&
           left->nid == right->nid;
}

static unsigned bucket(const struct kernel_lruvec_key *key)
{
    uint64_t value = key->memcg_id ^ ((uint64_t)(unsigned)key->nid << 32U) ^
                     (uint64_t)(unsigned)key->mode;
    value ^= value >> 30U;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27U;
    return (unsigned)(value % KERNEL_SNAPSHOT_BUCKETS);
}

static struct kernel_snapshot_store_entry *find_entry(
    const struct kernel_snapshot_store *store, const struct kernel_lruvec_key *key)
{
    struct kernel_snapshot_store_entry *entry;

    for (entry = store->buckets[bucket(key)]; entry != NULL; entry = entry->next) {
        if (key_equal(&entry->key, key)) return entry;
    }
    return NULL;
}

static bool scan_identity_equal(const struct kernel_lruvec_snapshot *left,
                                const struct kernel_lruvec_snapshot *right)
{
    return left->request_id == right->request_id &&
           left->priority_seq == right->priority_seq &&
           left->scan_seq == right->scan_seq;
}

static struct kernel_snapshot_history *find_scan_stage(
    const struct kernel_snapshot_store_entry *entry,
    const struct kernel_lruvec_snapshot *snapshot)
{
    struct kernel_snapshot_history *history;

    for (history = entry->history; history != NULL; history = history->next) {
        if (scan_identity_equal(&history->snapshot, snapshot) &&
            history->snapshot.stage == snapshot->stage)
            return history;
    }
    return NULL;
}

static struct kernel_snapshot_history *find_scan_other_stage(
    const struct kernel_snapshot_store_entry *entry,
    const struct kernel_lruvec_snapshot *snapshot)
{
    struct kernel_snapshot_history *history;
    enum kernel_snapshot_stage other =
        snapshot->stage == KERNEL_SNAPSHOT_SCAN_BEFORE ?
            KERNEL_SNAPSHOT_SCAN_AFTER : KERNEL_SNAPSHOT_SCAN_BEFORE;

    for (history = entry->history; history != NULL; history = history->next) {
        if (scan_identity_equal(&history->snapshot, snapshot) &&
            history->snapshot.stage == other)
            return history;
    }
    return NULL;
}

static int append_history(struct kernel_snapshot_store_entry *entry,
                          const struct kernel_lruvec_snapshot *snapshot)
{
    struct kernel_snapshot_history *history = calloc(1U, sizeof(*history));

    if (history == NULL) return -ENOMEM;
    history->snapshot = *snapshot;
    history->next = entry->history;
    entry->history = history;
    return 0;
}

void kernel_snapshot_store_init(struct kernel_snapshot_store *store)
{
    if (store != NULL) *store = (struct kernel_snapshot_store){0};
}

void kernel_snapshot_store_destroy(struct kernel_snapshot_store *store)
{
    size_t index;

    if (store == NULL) return;
    for (index = 0U; index < KERNEL_SNAPSHOT_BUCKETS; index++) {
        struct kernel_snapshot_store_entry *entry = store->buckets[index];

        while (entry != NULL) {
            struct kernel_snapshot_store_entry *next_entry = entry->next;
            struct kernel_snapshot_history *history = entry->history;

            while (history != NULL) {
                struct kernel_snapshot_history *next_history = history->next;
                free(history);
                history = next_history;
            }
            free(entry);
            entry = next_entry;
        }
        store->buckets[index] = NULL;
    }
    store->count = 0U;
    store->high_watermark = 0U;
}

int kernel_snapshot_store_ingest(
    struct kernel_snapshot_store *store,
    const struct kernel_lruvec_snapshot *snapshot,
    struct kernel_snapshot_ingest_result *result)
{
    struct kernel_snapshot_store_entry *entry;
    struct kernel_snapshot_store_entry **link;
    struct kernel_snapshot_history *same_stage;
    struct kernel_snapshot_history *other_stage;
    enum kernel_snapshot_ingest_status status = KERNEL_SNAPSHOT_ACCEPTED;
    bool scan_stage;

    if (store == NULL || snapshot == NULL || result == NULL) return -EINVAL;
    *result = (struct kernel_snapshot_ingest_result){0};
    entry = find_entry(store, &snapshot->key);
    if (entry != NULL && snapshot->key.mode == KERNEL_LRU_MODE_MEMCG &&
        entry->latest.memcg_css_id != snapshot->memcg_css_id)
        return result->status = KERNEL_SNAPSHOT_INCARCATION_CHANGED;

    scan_stage = snapshot->stage == KERNEL_SNAPSHOT_SCAN_BEFORE ||
                 snapshot->stage == KERNEL_SNAPSHOT_SCAN_AFTER;
    if (entry == NULL) {
        if (snapshot->stage == KERNEL_SNAPSHOT_SCAN_AFTER)
            return result->status = KERNEL_SNAPSHOT_STAGE_ORDER_ERROR;
        entry = calloc(1U, sizeof(*entry));
        if (entry == NULL) return -ENOMEM;
        entry->key = snapshot->key;
        link = &store->buckets[bucket(&snapshot->key)];
        entry->next = *link;
        *link = entry;
        store->count++;
    }

    if (scan_stage) {
        same_stage = find_scan_stage(entry, snapshot);
        if (same_stage != NULL) {
            result->previous_sequence = same_stage->snapshot.snapshot_seq;
            return result->status = KERNEL_SNAPSHOT_DUPLICATE;
        }
        other_stage = find_scan_other_stage(entry, snapshot);
        if (snapshot->stage == KERNEL_SNAPSHOT_SCAN_AFTER && other_stage == NULL) {
            return result->status = KERNEL_SNAPSHOT_STAGE_ORDER_ERROR;
        }
        if (snapshot->stage == KERNEL_SNAPSHOT_SCAN_BEFORE && other_stage != NULL) {
            return result->status = KERNEL_SNAPSHOT_STAGE_ORDER_ERROR;
        }
    } else if (entry->has_latest &&
               entry->latest.snapshot_seq == snapshot->snapshot_seq &&
               entry->latest.stage == snapshot->stage) {
        result->previous_sequence = entry->latest.snapshot_seq;
        return result->status = KERNEL_SNAPSHOT_DUPLICATE;
    }

    if (entry->has_latest) {
        result->previous_sequence = entry->latest.snapshot_seq;
        if (snapshot->snapshot_seq < entry->latest.snapshot_seq)
            return result->status = KERNEL_SNAPSHOT_STALE;
    }
    if (store->high_watermark != 0U && store->high_watermark != UINT64_MAX &&
        snapshot->snapshot_seq > store->high_watermark + 1U) {
        status = KERNEL_SNAPSHOT_PROVISIONAL_GAP;
        result->gap_count = snapshot->snapshot_seq - store->high_watermark - 1U;
    }
    if (scan_stage && append_history(entry, snapshot) != 0)
        return -ENOMEM;
    if (!entry->has_latest || snapshot->snapshot_seq > entry->latest.snapshot_seq) {
        entry->latest = *snapshot;
        entry->has_latest = true;
    }
    if (snapshot->snapshot_seq > store->high_watermark)
        store->high_watermark = snapshot->snapshot_seq;
    result->accepted = true;
    result->status = status;
    return result->status;
}

int kernel_snapshot_store_get_latest(
    const struct kernel_snapshot_store *store,
    const struct kernel_lruvec_key *key,
    struct kernel_lruvec_snapshot *out)
{
    struct kernel_snapshot_store_entry *entry;

    if (store == NULL || key == NULL || out == NULL) return -EINVAL;
    entry = find_entry(store, key);
    if (entry == NULL || !entry->has_latest) return -ENOENT;
    *out = entry->latest;
    return 0;
}
