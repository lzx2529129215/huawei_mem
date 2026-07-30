#ifndef MYSELF_KSWAPD_KERNEL_LRUVEC_SNAPSHOT_H
#define MYSELF_KSWAPD_KERNEL_LRUVEC_SNAPSHOT_H

#include <stddef.h>
#include <stdint.h>

enum kernel_lru_mode {
    KERNEL_LRU_MODE_MEMCG = 0,
    KERNEL_LRU_MODE_GLOBAL = 1
};

enum kernel_lruvec_scope {
    KERNEL_SCOPE_MEMCG_NODE = 1,
    KERNEL_SCOPE_NODE = 2
};

enum kernel_reclaim_source {
    KERNEL_RECLAIM_KSWAPD = 0,
    KERNEL_RECLAIM_DIRECT = 1,
    KERNEL_RECLAIM_MEMCG = 2,
    KERNEL_RECLAIM_UNKNOWN = 3
};

enum kernel_snapshot_stage {
    KERNEL_SNAPSHOT_SCAN_BEFORE = 0,
    KERNEL_SNAPSHOT_SCAN_AFTER = 1,
    KERNEL_SNAPSHOT_HEARTBEAT = 2,
    KERNEL_SNAPSHOT_DEBUGFS = 3
};

enum kernel_snapshot_consistency {
    KERNEL_SNAPSHOT_APPROXIMATE = 0,
    KERNEL_SNAPSHOT_LOCKED_SAMPLE = 1
};

enum kernel_lruvec_parse_status {
    KERNEL_LRUVEC_PARSE_OK = 0,
    KERNEL_LRUVEC_PARSE_NOT_LRUVEC_EVENT,
    KERNEL_LRUVEC_PARSE_MISSING_FIELD,
    KERNEL_LRUVEC_PARSE_INVALID_INTEGER,
    KERNEL_LRUVEC_PARSE_INVALID_ENUM,
    KERNEL_LRUVEC_PARSE_OVERFLOW,
    KERNEL_LRUVEC_PARSE_INVALID_KEY,
    KERNEL_LRUVEC_PARSE_INVALID_SCOPE
};

struct kernel_lruvec_key {
    enum kernel_lru_mode mode;
    uint64_t memcg_id;
    int nid;
};

struct kernel_lruvec_snapshot {
    uint64_t snapshot_seq;
    uint64_t timestamp_ns;
    uint64_t request_id;
    uint64_t priority_seq;
    uint64_t scan_seq;
    struct kernel_lruvec_key key;
    uint32_t memcg_css_id;
    enum kernel_reclaim_source reclaim_source;
    enum kernel_snapshot_stage stage;
    enum kernel_snapshot_consistency consistency;
    int priority;
    enum kernel_lruvec_scope lru_scope;
    enum kernel_lruvec_scope isolated_scope;
    uint64_t inactive_anon;
    uint64_t active_anon;
    uint64_t inactive_file;
    uint64_t active_file;
    uint64_t isolated_anon;
    uint64_t isolated_file;
    uint64_t scanned_total;
    uint64_t reclaimed_total;
    uint64_t field_valid_mask;
    uint64_t validation_flags;
};

struct kernel_lruvec_parse_error {
    enum kernel_lruvec_parse_status status;
    char field[32];
};

int kernel_lruvec_parse_trace_line(
    const char *line,
    struct kernel_lruvec_snapshot *out,
    struct kernel_lruvec_parse_error *error);

#endif
