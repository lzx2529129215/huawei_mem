#include "myself_kswapd/kernel_lruvec_snapshot.h"
#include "../test_support/test.h"

#include <stdio.h>
#include <string.h>

static const char *valid_snapshot(void)
{
    return "prefix myself_kswapd:lruvec_snapshot: "
           "snapshot_seq=7 timestamp_ns=11 request_id=13 priority_seq=2 "
           "scan_seq=3 mode=0 memcg_id=17 nid=2 memcg_css_id=23 "
           "reclaim_source=2 stage=0 consistency=0 priority=-4 "
           "lru_scope=1 isolated_scope=2 inactive_anon=31 active_anon=32 "
           "inactive_file=33 active_file=34 isolated_anon=35 "
           "isolated_file=36 scanned_total=37 reclaimed_total=38 "
           "field_valid_mask=0xff validation_flags=0";
}

static bool replace_field(char *line, size_t capacity,
                          const char *name, const char *value)
{
    char needle[64];
    char *begin;
    char *end;
    size_t old_length;
    size_t new_length;
    size_t tail_length;

    (void)snprintf(needle, sizeof(needle), "%s=", name);
    begin = strstr(line, needle);
    if (begin == NULL) return false;
    begin += strlen(needle);
    end = begin;
    while (*end != '\0' && *end != ' ' && *end != '\t') end++;
    old_length = (size_t)(end - begin);
    new_length = strlen(value);
    tail_length = strlen(end) + 1U;
    if (strlen(line) - old_length + new_length + 1U > capacity) return false;
    (void)memmove(begin + new_length, end, tail_length);
    (void)memcpy(begin, value, new_length);
    return true;
}

static bool test_lruvec_parser_valid_snapshot(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;

    TEST_ASSERT(kernel_lruvec_parse_trace_line(valid_snapshot(), &snapshot,
                                                &error) == KERNEL_LRUVEC_PARSE_OK);
    TEST_ASSERT_EQ_U64(7U, snapshot.snapshot_seq);
    TEST_ASSERT_EQ_U64(11U, snapshot.timestamp_ns);
    TEST_ASSERT_EQ_U64(13U, snapshot.request_id);
    TEST_ASSERT_EQ_U64(2U, snapshot.priority_seq);
    TEST_ASSERT_EQ_U64(3U, snapshot.scan_seq);
    TEST_ASSERT(snapshot.key.mode == KERNEL_LRU_MODE_MEMCG);
    TEST_ASSERT_EQ_U64(17U, snapshot.key.memcg_id);
    TEST_ASSERT(snapshot.key.nid == 2);
    TEST_ASSERT_EQ_U64(23U, snapshot.memcg_css_id);
    TEST_ASSERT(snapshot.reclaim_source == KERNEL_RECLAIM_MEMCG);
    TEST_ASSERT(snapshot.stage == KERNEL_SNAPSHOT_SCAN_BEFORE);
    TEST_ASSERT(snapshot.consistency == KERNEL_SNAPSHOT_APPROXIMATE);
    TEST_ASSERT(snapshot.priority == -4);
    TEST_ASSERT(snapshot.lru_scope == KERNEL_SCOPE_MEMCG_NODE);
    TEST_ASSERT(snapshot.isolated_scope == KERNEL_SCOPE_NODE);
    TEST_ASSERT_EQ_U64(31U, snapshot.inactive_anon);
    TEST_ASSERT_EQ_U64(32U, snapshot.active_anon);
    TEST_ASSERT_EQ_U64(33U, snapshot.inactive_file);
    TEST_ASSERT_EQ_U64(34U, snapshot.active_file);
    TEST_ASSERT_EQ_U64(35U, snapshot.isolated_anon);
    TEST_ASSERT_EQ_U64(36U, snapshot.isolated_file);
    TEST_ASSERT_EQ_U64(37U, snapshot.scanned_total);
    TEST_ASSERT_EQ_U64(38U, snapshot.reclaimed_total);
    TEST_ASSERT_EQ_U64(0xffU, snapshot.field_valid_mask);
    TEST_ASSERT_EQ_U64(0U, snapshot.validation_flags);
    return true;
}

static bool test_lruvec_parser_rejects_non_snapshot_event(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;

    TEST_ASSERT(kernel_lruvec_parse_trace_line(
                    "myself_kswapd:request_begin: request_id=9",
                    &snapshot, &error) == KERNEL_LRUVEC_PARSE_NOT_LRUVEC_EVENT);
    return true;
}

static bool test_lruvec_parser_missing_field(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;
    char line[1024];
    char *missing;

    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    missing = strstr(line, "reclaimed_total=");
    TEST_ASSERT(missing != NULL);
    *missing = '\0';
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_MISSING_FIELD);
    TEST_ASSERT(strcmp(error.field, "reclaimed_total") == 0);
    return true;
}

static bool test_lruvec_parser_invalid_integer_and_duplicate(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;
    char line[1024];

    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    (void)strcat(line, " snapshot_seq=8");
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_INVALID_KEY);
    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    TEST_ASSERT(replace_field(line, sizeof(line), "nid", "bad"));
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_INVALID_INTEGER);
    return true;
}

static bool test_lruvec_parser_invalid_enum_and_scope(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;
    char line[1024];

    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    TEST_ASSERT(replace_field(line, sizeof(line), "mode", "9"));
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_INVALID_ENUM);
    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    TEST_ASSERT(replace_field(line, sizeof(line), "lru_scope", "2"));
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_INVALID_SCOPE);
    return true;
}

static bool test_lruvec_parser_overflow_and_invalid_key(void)
{
    struct kernel_lruvec_snapshot snapshot;
    struct kernel_lruvec_parse_error error;
    char line[1200];

    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    TEST_ASSERT(replace_field(line, sizeof(line), "timestamp_ns",
                              "18446744073709551616"));
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_OVERFLOW);
    (void)snprintf(line, sizeof(line), "%s", valid_snapshot());
    TEST_ASSERT(replace_field(line, sizeof(line), "nid", "-1"));
    TEST_ASSERT(kernel_lruvec_parse_trace_line(line, &snapshot, &error) ==
                KERNEL_LRUVEC_PARSE_INVALID_KEY);
    return true;
}

void register_test_lruvec_trace_parser(void)
{
    reclaim_test_register("Linux lruvec trace parser", test_lruvec_parser_valid_snapshot);
    reclaim_test_register("lruvec parser non-event", test_lruvec_parser_rejects_non_snapshot_event);
    reclaim_test_register("lruvec parser missing field", test_lruvec_parser_missing_field);
    reclaim_test_register("lruvec parser integer and duplicate", test_lruvec_parser_invalid_integer_and_duplicate);
    reclaim_test_register("lruvec parser enum and scope", test_lruvec_parser_invalid_enum_and_scope);
    reclaim_test_register("lruvec parser overflow and key", test_lruvec_parser_overflow_and_invalid_key);
}
