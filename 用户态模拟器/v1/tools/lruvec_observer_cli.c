#include "myself_kswapd/kernel_snapshot_store.h"

#include <stdio.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

enum cli_mode { CLI_PARSE_ONLY, CLI_BOOTSTRAP, CLI_STRICT };
enum cli_output { CLI_JSONL, CLI_TSV };

static const char *status_name(enum kernel_snapshot_ingest_status status)
{
    static const char *const names[] = {
        "ACCEPTED", "DUPLICATE", "STALE", "PROVISIONAL_GAP",
        "STAGE_ORDER_ERROR", "INCARCATION_CHANGED"
    };
    return status >= 0 && (size_t)status < sizeof(names) / sizeof(names[0]) ?
           names[status] : "ERROR";
}

static void emit_record(enum cli_output output,
                        const struct kernel_lruvec_snapshot *snapshot,
                        const char *status)
{
    if (output == CLI_TSV) {
        (void)printf("lruvec_snapshot\t%" PRIu64 "\t%d\t%" PRIu64
                     "\t%d\t%s\n", snapshot->snapshot_seq,
                     snapshot->key.mode, snapshot->key.memcg_id,
                     snapshot->key.nid, status);
    } else {
        (void)printf("{\"event\":\"lruvec_snapshot\",\"snapshot_seq\":%" PRIu64 ","
                     "\"mode\":%d,\"memcg_id\":%" PRIu64 ",\"nid\":%d,"
                     "\"status\":\"%s\"}\n", snapshot->snapshot_seq,
                     snapshot->key.mode, snapshot->key.memcg_id,
                     snapshot->key.nid, status);
    }
}

static int parse_args(int argc, char **argv, const char **input,
                      enum cli_mode *mode, enum cli_output *output)
{
    int i;

    *input = "-";
    *mode = CLI_PARSE_ONLY;
    *output = CLI_JSONL;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--input") == 0 && i + 1 < argc) *input = argv[++i];
        else if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            const char *value = argv[++i];
            if (strcmp(value, "parse-only") == 0) *mode = CLI_PARSE_ONLY;
            else if (strcmp(value, "bootstrap") == 0) *mode = CLI_BOOTSTRAP;
            else if (strcmp(value, "strict") == 0) *mode = CLI_STRICT;
            else return -1;
        } else if (strcmp(argv[i], "--output") == 0 && i + 1 < argc) {
            const char *value = argv[++i];
            if (strcmp(value, "jsonl") == 0) *output = CLI_JSONL;
            else if (strcmp(value, "tsv") == 0) *output = CLI_TSV;
            else return -1;
        } else return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    const char *input_path;
    enum cli_mode mode;
    enum cli_output output;
    struct kernel_bootstrap_aggregate baseline;
    FILE *input;
    char line[8192];
    int exit_code = 0;

    if (parse_args(argc, argv, &input_path, &mode, &output) != 0) return 2;
    input = strcmp(input_path, "-") == 0 ? stdin : fopen(input_path, "rb");
    if (input == NULL) return 2;
    kernel_bootstrap_aggregate_init(&baseline);
    while (fgets(line, sizeof(line), input) != NULL) {
        struct kernel_lruvec_snapshot snapshot;
        struct kernel_lruvec_parse_error error;
        int parse_status = kernel_lruvec_parse_trace_line(line, &snapshot, &error);

        if (parse_status == KERNEL_LRUVEC_PARSE_NOT_LRUVEC_EVENT) continue;
        if (parse_status != KERNEL_LRUVEC_PARSE_OK) {
            if (output == CLI_TSV)
                (void)printf("parse_error\t%d\t%s\n", parse_status, error.field);
            else
                (void)printf("{\"event\":\"parse_error\",\"status\":%d,"
                             "\"field\":\"%s\"}\n", parse_status, error.field);
            exit_code = 1;
            continue;
        }
        if (mode == CLI_PARSE_ONLY) {
            emit_record(output, &snapshot, "PARSED");
        } else if (mode == CLI_BOOTSTRAP) {
            int status = kernel_bootstrap_aggregate_update(&baseline, &snapshot);
            emit_record(output, &snapshot, status_name(status));
        } else {
            emit_record(output, &snapshot, "MISSING_SHADOW_LRUVEC");
            exit_code = 2;
        }
    }
    kernel_bootstrap_aggregate_destroy(&baseline);
    if (input != stdin) (void)fclose(input);
    return exit_code;
}
