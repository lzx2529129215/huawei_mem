#include "myself_kswapd/kernel_snapshot_store.h"

void kernel_bootstrap_aggregate_init(struct kernel_bootstrap_aggregate *baseline)
{
    if (baseline == NULL) return;
    *baseline = (struct kernel_bootstrap_aggregate){0};
    kernel_snapshot_store_init(&baseline->store);
}

void kernel_bootstrap_aggregate_destroy(struct kernel_bootstrap_aggregate *baseline)
{
    if (baseline == NULL) return;
    kernel_snapshot_store_destroy(&baseline->store);
    *baseline = (struct kernel_bootstrap_aggregate){0};
}

int kernel_bootstrap_aggregate_update(
    struct kernel_bootstrap_aggregate *baseline,
    const struct kernel_lruvec_snapshot *snapshot)
{
    struct kernel_snapshot_ingest_result result;
    int status;

    if (baseline == NULL || snapshot == NULL) return -1;
    status = kernel_snapshot_store_ingest(&baseline->store, snapshot, &result);
    if (status >= 0) {
        if (result.accepted) baseline->accepted_count++;
        else baseline->rejected_count++;
    }
    return status;
}

int kernel_bootstrap_aggregate_get_latest(
    const struct kernel_bootstrap_aggregate *baseline,
    const struct kernel_lruvec_key *key,
    struct kernel_lruvec_snapshot *out)
{
    if (baseline == NULL) return -1;
    return kernel_snapshot_store_get_latest(&baseline->store, key, out);
}
