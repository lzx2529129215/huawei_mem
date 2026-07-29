#include "myself_kswapd/kernel_lruvec_snapshot.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum kernel_lruvec_field {
    FIELD_SNAPSHOT_SEQ,
    FIELD_TIMESTAMP_NS,
    FIELD_REQUEST_ID,
    FIELD_PRIORITY_SEQ,
    FIELD_SCAN_SEQ,
    FIELD_MODE,
    FIELD_MEMCG_ID,
    FIELD_NID,
    FIELD_MEMCG_CSS_ID,
    FIELD_RECLAIM_SOURCE,
    FIELD_STAGE,
    FIELD_CONSISTENCY,
    FIELD_PRIORITY,
    FIELD_LRU_SCOPE,
    FIELD_ISOLATED_SCOPE,
    FIELD_INACTIVE_ANON,
    FIELD_ACTIVE_ANON,
    FIELD_INACTIVE_FILE,
    FIELD_ACTIVE_FILE,
    FIELD_ISOLATED_ANON,
    FIELD_ISOLATED_FILE,
    FIELD_SCANNED_TOTAL,
    FIELD_RECLAIMED_TOTAL,
    FIELD_FIELD_VALID_MASK,
    FIELD_VALIDATION_FLAGS,
    FIELD_COUNT
};

struct kernel_lruvec_fields {
    const char *value[FIELD_COUNT];
    unsigned char seen[FIELD_COUNT];
};

static enum kernel_lruvec_parse_status fail(
    struct kernel_lruvec_parse_error *error,
    enum kernel_lruvec_parse_status status,
    const char *field)
{
    if (error != NULL) {
        error->status = status;
        (void)snprintf(error->field, sizeof(error->field), "%s",
                       field == NULL ? "" : field);
    }
    return status;
}

static int field_id(const char *name)
{
    static const char *const names[FIELD_COUNT] = {
        [FIELD_SNAPSHOT_SEQ] = "snapshot_seq",
        [FIELD_TIMESTAMP_NS] = "timestamp_ns",
        [FIELD_REQUEST_ID] = "request_id",
        [FIELD_PRIORITY_SEQ] = "priority_seq",
        [FIELD_SCAN_SEQ] = "scan_seq",
        [FIELD_MODE] = "mode",
        [FIELD_MEMCG_ID] = "memcg_id",
        [FIELD_NID] = "nid",
        [FIELD_MEMCG_CSS_ID] = "memcg_css_id",
        [FIELD_RECLAIM_SOURCE] = "reclaim_source",
        [FIELD_STAGE] = "stage",
        [FIELD_CONSISTENCY] = "consistency",
        [FIELD_PRIORITY] = "priority",
        [FIELD_LRU_SCOPE] = "lru_scope",
        [FIELD_ISOLATED_SCOPE] = "isolated_scope",
        [FIELD_INACTIVE_ANON] = "inactive_anon",
        [FIELD_ACTIVE_ANON] = "active_anon",
        [FIELD_INACTIVE_FILE] = "inactive_file",
        [FIELD_ACTIVE_FILE] = "active_file",
        [FIELD_ISOLATED_ANON] = "isolated_anon",
        [FIELD_ISOLATED_FILE] = "isolated_file",
        [FIELD_SCANNED_TOTAL] = "scanned_total",
        [FIELD_RECLAIMED_TOTAL] = "reclaimed_total",
        [FIELD_FIELD_VALID_MASK] = "field_valid_mask",
        [FIELD_VALIDATION_FLAGS] = "validation_flags"
    };
    int i;

    for (i = 0; i < FIELD_COUNT; i++) {
        if (strcmp(name, names[i]) == 0) {
            return i;
        }
    }
    return -1;
}

static enum kernel_lruvec_parse_status parse_u64(
    const char *text, uint64_t *out,
    struct kernel_lruvec_parse_error *error, const char *field)
{
    char *end;
    unsigned long long parsed;

    if (text == NULL || text[0] == '-' || text[0] == '+') {
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_INTEGER, field);
    }
    errno = 0;
    parsed = strtoull(text, &end, 0);
    if (errno == ERANGE) {
        return fail(error, KERNEL_LRUVEC_PARSE_OVERFLOW, field);
    }
    if (errno != 0 || end == text || *end != '\0') {
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_INTEGER, field);
    }
    *out = (uint64_t)parsed;
    return KERNEL_LRUVEC_PARSE_OK;
}

static enum kernel_lruvec_parse_status parse_i64(
    const char *text, int64_t *out,
    struct kernel_lruvec_parse_error *error, const char *field)
{
    char *end;
    long long parsed;

    if (text == NULL || text[0] == '\0') {
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_INTEGER, field);
    }
    errno = 0;
    parsed = strtoll(text, &end, 0);
    if (errno == ERANGE) {
        return fail(error, KERNEL_LRUVEC_PARSE_OVERFLOW, field);
    }
    if (errno != 0 || end == text || *end != '\0') {
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_INTEGER, field);
    }
    *out = (int64_t)parsed;
    return KERNEL_LRUVEC_PARSE_OK;
}

static enum kernel_lruvec_parse_status required_fields(
    const struct kernel_lruvec_fields *fields,
    struct kernel_lruvec_parse_error *error)
{
    int i;

    for (i = 0; i < FIELD_COUNT; i++) {
        if (!fields->seen[i]) {
            static const char *const names[FIELD_COUNT] = {
                "snapshot_seq", "timestamp_ns", "request_id",
                "priority_seq", "scan_seq", "mode", "memcg_id", "nid",
                "memcg_css_id", "reclaim_source", "stage", "consistency",
                "priority", "lru_scope", "isolated_scope", "inactive_anon",
                "active_anon", "inactive_file", "active_file", "isolated_anon",
                "isolated_file", "scanned_total", "reclaimed_total",
                "field_valid_mask", "validation_flags"
            };
            return fail(error, KERNEL_LRUVEC_PARSE_MISSING_FIELD, names[i]);
        }
    }
    return KERNEL_LRUVEC_PARSE_OK;
}

static enum kernel_lruvec_parse_status parse_values(
    const struct kernel_lruvec_fields *fields,
    struct kernel_lruvec_snapshot *snapshot,
    struct kernel_lruvec_parse_error *error)
{
    uint64_t value;
    int64_t signed_value;
    enum kernel_lruvec_parse_status status;

#define U64_FIELD(id, member) \
    do { \
        status = parse_u64(fields->value[(id)], &(snapshot->member), error, #member); \
        if (status != KERNEL_LRUVEC_PARSE_OK) return status; \
    } while (0)
#define ENUM_FIELD(id, member) \
    do { \
        status = parse_i64(fields->value[(id)], &signed_value, error, #member); \
        if (status != KERNEL_LRUVEC_PARSE_OK || signed_value < INT_MIN || signed_value > INT_MAX) { \
            if (status == KERNEL_LRUVEC_PARSE_OK) status = KERNEL_LRUVEC_PARSE_INVALID_ENUM; \
            return status == KERNEL_LRUVEC_PARSE_OK ? fail(error, status, #member) : status; \
        } \
        snapshot->member = (int)signed_value; \
    } while (0)

    U64_FIELD(FIELD_SNAPSHOT_SEQ, snapshot_seq);
    U64_FIELD(FIELD_TIMESTAMP_NS, timestamp_ns);
    U64_FIELD(FIELD_REQUEST_ID, request_id);
    U64_FIELD(FIELD_PRIORITY_SEQ, priority_seq);
    U64_FIELD(FIELD_SCAN_SEQ, scan_seq);
    U64_FIELD(FIELD_MEMCG_ID, key.memcg_id);
    U64_FIELD(FIELD_INACTIVE_ANON, inactive_anon);
    U64_FIELD(FIELD_ACTIVE_ANON, active_anon);
    U64_FIELD(FIELD_INACTIVE_FILE, inactive_file);
    U64_FIELD(FIELD_ACTIVE_FILE, active_file);
    U64_FIELD(FIELD_ISOLATED_ANON, isolated_anon);
    U64_FIELD(FIELD_ISOLATED_FILE, isolated_file);
    U64_FIELD(FIELD_SCANNED_TOTAL, scanned_total);
    U64_FIELD(FIELD_RECLAIMED_TOTAL, reclaimed_total);
    U64_FIELD(FIELD_FIELD_VALID_MASK, field_valid_mask);
    U64_FIELD(FIELD_VALIDATION_FLAGS, validation_flags);
    status = parse_u64(fields->value[FIELD_MEMCG_CSS_ID], &value, error,
                       "memcg_css_id");
    if (status != KERNEL_LRUVEC_PARSE_OK || value > UINT32_MAX) {
        return status == KERNEL_LRUVEC_PARSE_OK ?
            fail(error, KERNEL_LRUVEC_PARSE_OVERFLOW, "memcg_css_id") : status;
    }
    snapshot->memcg_css_id = (uint32_t)value;
    status = parse_i64(fields->value[FIELD_NID], &signed_value, error, "nid");
    if (status != KERNEL_LRUVEC_PARSE_OK) return status;
    if (signed_value < 0 || signed_value > INT_MAX)
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_KEY, "nid");
    snapshot->key.nid = (int)signed_value;
    ENUM_FIELD(FIELD_MODE, key.mode);
    ENUM_FIELD(FIELD_RECLAIM_SOURCE, reclaim_source);
    ENUM_FIELD(FIELD_STAGE, stage);
    ENUM_FIELD(FIELD_CONSISTENCY, consistency);
    ENUM_FIELD(FIELD_PRIORITY, priority);
    ENUM_FIELD(FIELD_LRU_SCOPE, lru_scope);
    ENUM_FIELD(FIELD_ISOLATED_SCOPE, isolated_scope);
#undef U64_FIELD
#undef ENUM_FIELD

    if (snapshot->key.mode < KERNEL_LRU_MODE_MEMCG ||
        snapshot->key.mode > KERNEL_LRU_MODE_GLOBAL ||
        snapshot->reclaim_source < KERNEL_RECLAIM_KSWAPD ||
        snapshot->reclaim_source > KERNEL_RECLAIM_UNKNOWN ||
        snapshot->stage < KERNEL_SNAPSHOT_SCAN_BEFORE ||
        snapshot->stage > KERNEL_SNAPSHOT_DEBUGFS ||
        snapshot->consistency < KERNEL_SNAPSHOT_APPROXIMATE ||
        snapshot->consistency > KERNEL_SNAPSHOT_LOCKED_SAMPLE)
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_ENUM, "enum");
    if (snapshot->lru_scope < KERNEL_SCOPE_MEMCG_NODE ||
        snapshot->lru_scope > KERNEL_SCOPE_NODE ||
        snapshot->isolated_scope < KERNEL_SCOPE_MEMCG_NODE ||
        snapshot->isolated_scope > KERNEL_SCOPE_NODE)
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_SCOPE, "scope");
    if ((snapshot->key.mode == KERNEL_LRU_MODE_MEMCG &&
         (snapshot->lru_scope != KERNEL_SCOPE_MEMCG_NODE ||
          snapshot->isolated_scope != KERNEL_SCOPE_NODE)) ||
        (snapshot->key.mode == KERNEL_LRU_MODE_GLOBAL &&
         (snapshot->lru_scope != KERNEL_SCOPE_NODE ||
          snapshot->isolated_scope != KERNEL_SCOPE_NODE)))
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_SCOPE, "scope");
    if (snapshot->stage <= KERNEL_SNAPSHOT_SCAN_AFTER) {
        if (!snapshot->request_id || !snapshot->priority_seq || !snapshot->scan_seq)
            return fail(error, KERNEL_LRUVEC_PARSE_INVALID_KEY, "scan_ids");
    } else if (snapshot->request_id || snapshot->priority_seq || snapshot->scan_seq) {
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_KEY, "ambient_ids");
    }
    return KERNEL_LRUVEC_PARSE_OK;
}

static char *next_token(char **cursor)
{
    char *start;

    while (**cursor == ' ' || **cursor == '\t' || **cursor == '\r' ||
           **cursor == '\n') {
        (*cursor)++;
    }
    if (**cursor == '\0') return NULL;
    start = *cursor;
    while (**cursor != '\0' && **cursor != ' ' && **cursor != '\t' &&
           **cursor != '\r' && **cursor != '\n') {
        (*cursor)++;
    }
    if (**cursor != '\0') {
        **cursor = '\0';
        (*cursor)++;
    }
    return start;
}

int kernel_lruvec_parse_trace_line(
    const char *line,
    struct kernel_lruvec_snapshot *out,
    struct kernel_lruvec_parse_error *error)
{
    static const char marker[] = "myself_kswapd:lruvec_snapshot:";
    struct kernel_lruvec_fields fields = {0};
    char work[4096];
    char *cursor;
    char *token;
    const char *payload;
    size_t length;
    int id;
    enum kernel_lruvec_parse_status status;

    if (out != NULL) *out = (struct kernel_lruvec_snapshot){0};
    if (error != NULL) *error = (struct kernel_lruvec_parse_error){0};
    if (line == NULL || out == NULL)
        return fail(error, KERNEL_LRUVEC_PARSE_INVALID_KEY, "argument");
    payload = strstr(line, marker);
    if (payload == NULL)
        return fail(error, KERNEL_LRUVEC_PARSE_NOT_LRUVEC_EVENT, "event");
    payload += sizeof(marker) - 1U;
    length = strlen(payload);
    if (length >= sizeof(work))
        return fail(error, KERNEL_LRUVEC_PARSE_OVERFLOW, "line");
    (void)memcpy(work, payload, length + 1U);
    cursor = work;
    while ((token = next_token(&cursor)) != NULL) {
        char *separator = strchr(token, '=');
        if (separator == NULL) continue;
        *separator = '\0';
        id = field_id(token);
        if (id < 0) continue;
        if (fields.seen[id])
            return fail(error, KERNEL_LRUVEC_PARSE_INVALID_KEY, token);
        fields.seen[id] = 1U;
        fields.value[id] = separator + 1;
    }
    status = required_fields(&fields, error);
    if (status != KERNEL_LRUVEC_PARSE_OK) return status;
    return parse_values(&fields, out, error);
}
