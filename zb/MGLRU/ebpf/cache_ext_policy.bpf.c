// SPDX-License-Identifier: GPL-2.0
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

#define CACHE_EXT_SKIP_CTX
#include "cache_ext_bpf_common.h"

char LICENSE[] SEC("license") = "GPL";

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, 128);
	__type(key, unsigned short);
	__type(value, struct cache_ext_hist_val);
} history_map SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, 16384);
	__type(key, struct cache_ext_markov_key);
	__type(value, struct cache_ext_markov_val);
} markov_map SEC(".maps");

struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, 8192);
	__type(key, struct cache_ext_profile_key);
	__type(value, struct cache_ext_profile_val);
} profile_map SEC(".maps");

SEC("fmod_ret/cache_ext_bpf_decide")
int BPF_PROG(cache_ext_policy_compat, struct cache_ext_bpf_ctx *bpf_ctx)
{
	(void)bpf_ctx;

	return 0;
}

SEC("fmod_ret/cache_ext_bpf_predict")
int BPF_PROG(cache_ext_predict_policy, struct cache_ext_bpf_cycle_ctx *cycle_ctx)
{
	struct cache_ext_markov_key mkey = {};
	struct cache_ext_markov_val *mval;
	struct cache_ext_hist_val *hist;
	unsigned short app_id;

	if (!cycle_ctx)
		return 0;

	app_id = cycle_ctx->app_id;
	if (!app_id)
		return 0;

	hist = bpf_map_lookup_elem(&history_map, &app_id);
	if (!hist || hist->len < CACHE_EXT_HIST_LEN)
		return 0;

	mkey.app_id = app_id;
	mkey.ctx[0] = hist->ops[0];
	mkey.ctx[1] = hist->ops[1];
	mkey.ctx[2] = hist->ops[2];
	mkey.ctx[3] = hist->ops[3];

	mval = bpf_map_lookup_elem(&markov_map, &mkey);
	if (!mval || !mval->next_op)
		return 0;

	return mval->next_op;
}
