#ifndef MYSELF_KSWAPD_KERNEL_SNAPSHOT_STORE_H
#define MYSELF_KSWAPD_KERNEL_SNAPSHOT_STORE_H

#include "myself_kswapd/kernel_lruvec_snapshot.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum kernel_snapshot_ingest_status {
    KERNEL_SNAPSHOT_ACCEPTED = 0,
    KERNEL_SNAPSHOT_DUPLICATE,
    KERNEL_SNAPSHOT_STALE,
    KERNEL_SNAPSHOT_PROVISIONAL_GAP,
    KERNEL_SNAPSHOT_STAGE_ORDER_ERROR,
    KERNEL_SNAPSHOT_INCARCATION_CHANGED
};

struct kernel_snapshot_ingest_result {
    enum kernel_snapshot_ingest_status status;
    bool accepted;
    uint64_t previous_sequence;
    uint64_t gap_count;
};

struct kernel_snapshot_store_entry;

struct kernel_snapshot_store {
    struct kernel_snapshot_store_entry *buckets[64];
    size_t count;
    uint64_t high_watermark;
};

void kernel_snapshot_store_init(struct kernel_snapshot_store *store);
void kernel_snapshot_store_destroy(struct kernel_snapshot_store *store);
int kernel_snapshot_store_ingest(
    struct kernel_snapshot_store *store,
    const struct kernel_lruvec_snapshot *snapshot,
    struct kernel_snapshot_ingest_result *result);
int kernel_snapshot_store_get_latest(
    const struct kernel_snapshot_store *store,
    const struct kernel_lruvec_key *key,
    struct kernel_lruvec_snapshot *out);

#endif
