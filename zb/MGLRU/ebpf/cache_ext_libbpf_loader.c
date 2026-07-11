// SPDX-License-Identifier: GPL-2.0
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <bpf/bpf.h>
#include <bpf/libbpf.h>

#include "cache_ext_bpf_common.h"

#define MAX_LINE 1024
#define MAX_FIELDS 32

static volatile sig_atomic_t exiting;

struct options {
	unsigned short app_id;
	const char *markov_csv;
	const char *profile_csv;
	const char *debugfs;
	const char *bpf_obj;
	long limit;
	bool has_set_history;
	unsigned short set_history[CACHE_EXT_HIST_LEN];
};

static void on_signal(int signo)
{
	(void)signo;
	exiting = 1;
}

static void usage(const char *prog)
{
	fprintf(stderr,
		"Usage: %s --app-id ID --markov-csv PATH --profile-csv PATH "
		"--debugfs PATH --bpf-obj PATH [--limit N] "
		"[--set-history A B C D]\n",
		prog);
}

static int parse_u64(const char *s, unsigned long long *out)
{
	char *end = NULL;
	errno = 0;
	*out = strtoull(s, &end, 0);
	return errno || end == s || *end != '\0' ? -1 : 0;
}

static int parse_u16(const char *s, unsigned short *out)
{
	unsigned long long v;

	if (parse_u64(s, &v) || v > USHRT_MAX)
		return -1;
	*out = (unsigned short)v;
	return 0;
}

static int parse_u32(const char *s, unsigned int *out)
{
	unsigned long long v;

	if (parse_u64(s, &v) || v > UINT_MAX)
		return -1;
	*out = (unsigned int)v;
	return 0;
}

static int split_csv_line(char *line, char **fields, int max_fields)
{
	int n = 0;
	char *p = line;

	line[strcspn(line, "\r\n")] = '\0';
	while (n < max_fields) {
		fields[n++] = p;
		p = strchr(p, ',');
		if (!p)
			break;
		*p++ = '\0';
	}
	return n;
}

static void strip_utf8_bom(char **field)
{
	unsigned char *p = (unsigned char *)*field;

	if (p[0] == 0xef && p[1] == 0xbb && p[2] == 0xbf)
		*field += 3;
}

static int find_field(char **fields, int n, const char *name)
{
	int i;

	for (i = 0; i < n; i++) {
		if (strcmp(fields[i], name) == 0)
			return i;
	}
	return -1;
}

static int require_field(char **fields, int n, const char *name)
{
	int idx = find_field(fields, n, name);

	if (idx < 0)
		fprintf(stderr, "missing CSV field: %s\n", name);
	return idx;
}

static int update_history_map(int fd, unsigned short app_id,
			      const unsigned short *history, int len)
{
	struct cache_ext_hist_val val = {};
	int i;

	if (len > CACHE_EXT_HIST_LEN)
		len = CACHE_EXT_HIST_LEN;
	for (i = 0; i < len; i++)
		val.ops[i] = history[i];
	val.len = (unsigned char)len;

	return bpf_map_update_elem(fd, &app_id, &val, BPF_ANY);
}

static int write_debugfs_line(const char *path, const char *line);

static int load_markov_csv(const char *path, int fd, long limit)
{
	FILE *f = fopen(path, "r");
	char line[MAX_LINE];
	char *fields[MAX_FIELDS];
	int n, idx_app, idx_ctx0, idx_ctx1, idx_ctx2, idx_ctx3, idx_next, idx_count;
	long entries = 0;

	if (!f) {
		perror(path);
		return -1;
	}

	if (!fgets(line, sizeof(line), f)) {
		fprintf(stderr, "%s: empty CSV\n", path);
		fclose(f);
		return -1;
	}
	n = split_csv_line(line, fields, MAX_FIELDS);
	if (n > 0)
		strip_utf8_bom(&fields[0]);
	idx_app = require_field(fields, n, "app_id");
	idx_ctx0 = require_field(fields, n, "ctx0");
	idx_ctx1 = require_field(fields, n, "ctx1");
	idx_ctx2 = require_field(fields, n, "ctx2");
	idx_ctx3 = require_field(fields, n, "ctx3");
	idx_next = require_field(fields, n, "next_op");
	idx_count = require_field(fields, n, "count");
	if (idx_app < 0 || idx_ctx0 < 0 || idx_ctx1 < 0 || idx_ctx2 < 0 ||
	    idx_ctx3 < 0 || idx_next < 0 || idx_count < 0) {
		fclose(f);
		return -1;
	}

	while (fgets(line, sizeof(line), f)) {
		struct cache_ext_markov_key key = {};
		struct cache_ext_markov_val val = {};
		struct cache_ext_markov_val old = {};
		unsigned short app_id, ctx0, ctx1, ctx2, ctx3, next_op;
		unsigned int count;
		bool exists;
		bool should_update = true;

		n = split_csv_line(line, fields, MAX_FIELDS);
		if (n <= idx_count)
			continue;
		if (parse_u16(fields[idx_app], &app_id) ||
		    parse_u16(fields[idx_ctx0], &ctx0) ||
		    parse_u16(fields[idx_ctx1], &ctx1) ||
		    parse_u16(fields[idx_ctx2], &ctx2) ||
		    parse_u16(fields[idx_ctx3], &ctx3) ||
		    parse_u16(fields[idx_next], &next_op) ||
		    parse_u32(fields[idx_count], &count)) {
			fprintf(stderr, "%s: invalid markov row\n", path);
			fclose(f);
			return -1;
		}

		key.app_id = app_id;
		key.ctx[0] = ctx0;
		key.ctx[1] = ctx1;
		key.ctx[2] = ctx2;
		key.ctx[3] = ctx3;

		exists = bpf_map_lookup_elem(fd, &key, &old) == 0;
		if (!exists && errno != ENOENT) {
			perror("bpf_map_lookup_elem(markov_map)");
			fclose(f);
			return -1;
		}
		if (!exists && limit >= 0 && entries >= limit)
			continue;
		if (exists)
			should_update = count > old.count ||
					(count == old.count && next_op < old.next_op);
		if (!should_update)
			continue;

		val.next_op = next_op;
		val.count = count;
		if (bpf_map_update_elem(fd, &key, &val, BPF_ANY)) {
			perror("bpf_map_update_elem(markov_map)");
			fclose(f);
			return -1;
		}
		if (!exists)
			entries++;
	}

	fclose(f);
	printf("markov top-1 entries: %ld\n", entries);
	return 0;
}

struct loaded_profile {
	struct cache_ext_profile_key key;
	struct cache_ext_profile_val val;
};

static int find_loaded_profile(struct loaded_profile *profiles, long count,
			       const struct cache_ext_profile_key *key)
{
	long i;

	for (i = 0; i < count; i++) {
		if (profiles[i].key.app_id == key->app_id &&
		    profiles[i].key.op_id == key->op_id &&
		    profiles[i].key.dev_major == key->dev_major &&
		    profiles[i].key.dev_minor == key->dev_minor &&
		    profiles[i].key.ino == key->ino)
			return (int)i;
	}
	return -1;
}

static int load_profile_csv(const char *path, int fd, const char *debugfs)
{
	FILE *f = fopen(path, "r");
	char line[MAX_LINE];
	char *fields[MAX_FIELDS];
	struct loaded_profile *profiles = NULL;
	int n, idx_app, idx_op, idx_major, idx_minor, idx_ino;
	int idx_start, idx_end, idx_priority;
	long entries = 0;
	long capacity = 0;
	long i;
	int ret = -1;

	if (!f) {
		fprintf(stderr, "WARNING: profile CSV not found or empty; kernel profile hints will be empty.\n");
		printf("profile entries: 0\n");
		return 0;
	}

	if (!fgets(line, sizeof(line), f)) {
		fclose(f);
		printf("profile entries: 0\n");
		return 0;
	}
	n = split_csv_line(line, fields, MAX_FIELDS);
	if (n > 0)
		strip_utf8_bom(&fields[0]);
	idx_app = require_field(fields, n, "app_id");
	idx_op = require_field(fields, n, "op_id");
	idx_major = require_field(fields, n, "dev_major");
	idx_minor = require_field(fields, n, "dev_minor");
	idx_ino = require_field(fields, n, "ino");
	idx_start = require_field(fields, n, "index_start");
	idx_end = require_field(fields, n, "index_end");
	idx_priority = require_field(fields, n, "priority");
	if (idx_app < 0 || idx_op < 0 || idx_major < 0 || idx_minor < 0 ||
	    idx_ino < 0 || idx_start < 0 || idx_end < 0 || idx_priority < 0) {
		goto out;
	}

	while (fgets(line, sizeof(line), f)) {
		struct cache_ext_profile_key key = {};
		struct cache_ext_profile_val val = {};
		unsigned long long ino, start, end;
		int pos;

		n = split_csv_line(line, fields, MAX_FIELDS);
		if (n <= idx_priority)
			continue;
		if (parse_u16(fields[idx_app], &key.app_id) ||
		    parse_u16(fields[idx_op], &key.op_id) ||
		    parse_u32(fields[idx_major], &key.dev_major) ||
		    parse_u32(fields[idx_minor], &key.dev_minor) ||
		    parse_u64(fields[idx_ino], &ino) ||
		    parse_u64(fields[idx_start], &start) ||
		    parse_u64(fields[idx_end], &end) ||
		    parse_u16(fields[idx_priority], &val.priority)) {
			fprintf(stderr, "%s: invalid profile row\n", path);
			goto out;
		}
		if (start > end) {
			fprintf(stderr, "%s: index_start > index_end\n", path);
			goto out;
		}

		key.ino = ino;
		val.index_start = start;
		val.index_end = end;

		pos = find_loaded_profile(profiles, entries, &key);
		if (pos >= 0) {
			struct cache_ext_profile_val *old = &profiles[pos].val;

			if (old->index_start < val.index_start)
				val.index_start = old->index_start;
			if (old->index_end > val.index_end)
				val.index_end = old->index_end;
			if (old->priority < val.priority)
				val.priority = old->priority;
			*old = val;
			continue;
		}

		if (entries == capacity) {
			struct loaded_profile *new_profiles;
			long new_capacity = capacity ? capacity * 2 : 256;

			new_profiles = realloc(profiles,
					       sizeof(*profiles) * new_capacity);
			if (!new_profiles) {
				perror("realloc(profile)");
				goto out;
			}
			profiles = new_profiles;
			capacity = new_capacity;
		}

		profiles[entries].key = key;
		profiles[entries].val = val;
		entries++;
	}

	for (i = 0; i < entries; i++) {
		char cmd[256];

		if (fd >= 0 && bpf_map_update_elem(fd, &profiles[i].key,
						   &profiles[i].val, BPF_ANY)) {
			perror("bpf_map_update_elem(profile_map)");
			goto out;
		}

		snprintf(cmd, sizeof(cmd),
			 "profile add %u %u %u %u %llu %llu %llu %u",
			 profiles[i].key.app_id, profiles[i].key.op_id,
			 profiles[i].key.dev_major, profiles[i].key.dev_minor,
			 profiles[i].key.ino, profiles[i].val.index_start,
			 profiles[i].val.index_end, profiles[i].val.priority);
		if (write_debugfs_line(debugfs, cmd)) {
			fprintf(stderr, "failed to sync profile hint %ld to debugfs\n", i);
			goto out;
		}
	}

	ret = 0;

out:
	free(profiles);
	fclose(f);
	if (!ret)
		printf("profile entries synced to kernel hints: %ld\n", entries);
	return ret;
}

static int write_debugfs_line(const char *path, const char *line)
{
	FILE *f = fopen(path, "w");

	if (!f) {
		perror(path);
		return -1;
	}
	if (fprintf(f, "%s\n", line) < 0) {
		perror("write debugfs");
		fclose(f);
		return -1;
	}
	if (fclose(f)) {
		perror("close debugfs");
		return -1;
	}
	return 0;
}

static int configure_debugfs(const char *path, unsigned short app_id)
{
	char app_line[64];

	snprintf(app_line, sizeof(app_line), "app %u", app_id);
	if (write_debugfs_line(path, "enable 1") ||
	    write_debugfs_line(path, app_line) ||
	    write_debugfs_line(path, "policy bpf") ||
	    write_debugfs_line(path, "bpf enable 1"))
		return -1;
	return 0;
}

static int interactive_history(int history_fd, unsigned short app_id)
{
	unsigned short history[CACHE_EXT_HIST_LEN] = {};
	int len = 0;
	char line[128];

	while (!exiting) {
		unsigned short op;
		int i;

		printf("input op_id > ");
		fflush(stdout);
		if (!fgets(line, sizeof(line), stdin)) {
			printf("\n");
			return 0;
		}
		line[strcspn(line, "\r\n")] = '\0';
		if (!line[0])
			continue;
		if (!strcmp(line, "q") || !strcmp(line, "quit") || !strcmp(line, "exit"))
			return 0;
		if (parse_u16(line, &op)) {
			fprintf(stderr, "invalid op_id: %s\n", line);
			continue;
		}

		if (len < CACHE_EXT_HIST_LEN)
			history[len++] = op;
		else {
			memmove(history, history + 1, sizeof(history[0]) * (CACHE_EXT_HIST_LEN - 1));
			history[CACHE_EXT_HIST_LEN - 1] = op;
		}

		if (update_history_map(history_fd, app_id, history, len)) {
			perror("bpf_map_update_elem(history_map)");
			return -1;
		}
		printf("history:");
		for (i = 0; i < len; i++)
			printf(" %u", history[i]);
		printf("\n");
		if (len == CACHE_EXT_HIST_LEN) {
			printf("history_map updated: app=%u ops=%u %u %u %u\n",
			       app_id, history[0], history[1], history[2], history[3]);
		}
	}
	return 0;
}

static int parse_args(int argc, char **argv, struct options *opts)
{
	int i;

	opts->debugfs = "/sys/kernel/debug/cache_ext";
	opts->limit = -1;

	for (i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--app-id") && i + 1 < argc) {
			if (parse_u16(argv[++i], &opts->app_id))
				return -1;
		} else if (!strcmp(argv[i], "--markov-csv") && i + 1 < argc) {
			opts->markov_csv = argv[++i];
		} else if (!strcmp(argv[i], "--profile-csv") && i + 1 < argc) {
			opts->profile_csv = argv[++i];
		} else if (!strcmp(argv[i], "--debugfs") && i + 1 < argc) {
			opts->debugfs = argv[++i];
		} else if (!strcmp(argv[i], "--bpf-obj") && i + 1 < argc) {
			opts->bpf_obj = argv[++i];
		} else if (!strcmp(argv[i], "--limit") && i + 1 < argc) {
			char *end = NULL;
			errno = 0;
			opts->limit = strtol(argv[++i], &end, 0);
			if (errno || end == argv[i] || *end != '\0')
				return -1;
		} else if (!strcmp(argv[i], "--set-history") && i + CACHE_EXT_HIST_LEN < argc) {
			int j;

			opts->has_set_history = true;
			for (j = 0; j < CACHE_EXT_HIST_LEN; j++) {
				if (parse_u16(argv[++i], &opts->set_history[j]))
					return -1;
			}
		} else {
			return -1;
		}
	}

	if (!opts->app_id || !opts->markov_csv || !opts->profile_csv || !opts->bpf_obj)
		return -1;
	return 0;
}

static int find_map_fd(struct bpf_object *obj, const char *name)
{
	struct bpf_map *map = bpf_object__find_map_by_name(obj, name);
	int fd;

	if (!map) {
		fprintf(stderr, "map not found: %s\n", name);
		return -1;
	}
	fd = bpf_map__fd(map);
	if (fd < 0)
		fprintf(stderr, "map fd invalid: %s\n", name);
	return fd;
}

int main(int argc, char **argv)
{
	struct options opts = {};
	struct bpf_object *obj = NULL;
	struct bpf_program *prog = NULL;
	struct bpf_link *link = NULL;
	int history_fd, markov_fd, profile_fd;
	int err = 1;

	if (parse_args(argc, argv, &opts)) {
		usage(argv[0]);
		return 1;
	}

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	libbpf_set_strict_mode(LIBBPF_STRICT_ALL);

	obj = bpf_object__open_file(opts.bpf_obj, NULL);
	if (libbpf_get_error(obj)) {
		fprintf(stderr, "failed to open BPF object: %s\n", opts.bpf_obj);
		obj = NULL;
		goto out;
	}

	if (bpf_object__load(obj)) {
		fprintf(stderr, "failed to load BPF object: %s\n", opts.bpf_obj);
		goto out;
	}

	prog = bpf_object__find_program_by_name(obj, "cache_ext_predict_policy");
	if (!prog)
		prog = bpf_object__find_program_by_name(obj, "cache_ext_policy");
	if (!prog)
		prog = bpf_object__next_program(obj, NULL);
	if (!prog) {
		fprintf(stderr, "failed to find BPF program\n");
		goto out;
	}

	link = bpf_program__attach(prog);
	if (libbpf_get_error(link)) {
		fprintf(stderr, "failed to attach fmod_ret/cache_ext_bpf_predict\n");
		link = NULL;
		goto out;
	}

	history_fd = find_map_fd(obj, "history_map");
	markov_fd = find_map_fd(obj, "markov_map");
	profile_fd = find_map_fd(obj, "profile_map");
	if (history_fd < 0 || markov_fd < 0 || profile_fd < 0)
		goto out;

	printf("bpf_obj: %s\n", opts.bpf_obj);
	printf("debugfs: %s\n", opts.debugfs);
	printf("app_id: %u\n", opts.app_id);
	printf("attached to fmod_ret/cache_ext_bpf_predict\n");

	if (configure_debugfs(opts.debugfs, opts.app_id))
		goto out;
	if (write_debugfs_line(opts.debugfs, "profile clear"))
		goto out;

	if (load_markov_csv(opts.markov_csv, markov_fd, opts.limit) ||
	    load_profile_csv(opts.profile_csv, profile_fd, opts.debugfs))
		goto out;

	if (opts.has_set_history) {
		if (update_history_map(history_fd, opts.app_id, opts.set_history,
				       CACHE_EXT_HIST_LEN)) {
			perror("bpf_map_update_elem(history_map)");
			goto out;
		}
		printf("history_map updated: app=%u ops=%u %u %u %u\n",
		       opts.app_id, opts.set_history[0], opts.set_history[1],
		       opts.set_history[2], opts.set_history[3]);
		printf("holding BPF link; press Ctrl+C to exit\n");
		while (!exiting)
			pause();
		err = 0;
		goto out;
	}

	err = interactive_history(history_fd, opts.app_id) ? 1 : 0;

out:
	bpf_link__destroy(link);
	bpf_object__close(obj);
	return err;
}
