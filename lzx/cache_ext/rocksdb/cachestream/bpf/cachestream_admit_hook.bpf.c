#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

char _license[] SEC("license") = "GPL";

#define BPF_STRUCT_OPS(name, args...) \
	SEC("struct_ops/" #name)      \
	BPF_PROG(name, args)

#define BPF_STRUCT_OPS_SLEEPABLE(name, args...) \
	SEC("struct_ops.s/" #name)              \
	BPF_PROG(name, args)

#define MAX_ENTRIES 1000
#define BYPASS_MIN_SIZE (16 * 1024)
#define SEQ_TOLERANCE (128 * 1024)
#define BYPASS_ALL 1

// Map to track bypassed thread IDs
struct {
	__uint(type, BPF_MAP_TYPE_HASH);
	__uint(max_entries, MAX_ENTRIES);	
	__type(key, __u32);
	__type(value, __u8);
} bypassed_tids SEC(".maps");

#if !BYPASS_ALL
struct read_key {
	__u64 ino;
	__u32 tid;
	__u32 pad;
};

struct read_state {
	__u64 offset;
	__u64 size;
};

// Track last read per (tid, ino) to detect sequential access
struct {
	__uint(type, BPF_MAP_TYPE_LRU_HASH);
	__uint(max_entries, MAX_ENTRIES);
	__type(key, struct read_key);
	__type(value, struct read_state);
} last_reads SEC(".maps");
#endif

#ifdef BPF_DEBUG
// Map to track admission statistics
// Key 0: count of bypassed admissions (returned true)
// Key 1: count of normal admissions (returned false)
struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__uint(max_entries, 2);
	__type(key, __u32);
	__type(value, __u64);
} admission_stats SEC(".maps");
#endif

s32 BPF_STRUCT_OPS_SLEEPABLE(admit_hook_init, struct mem_cgroup *memcg)
{
	return 0;
}

void BPF_STRUCT_OPS(admit_hook_evict_folios, struct cache_ext_eviction_ctx *eviction_ctx,
		    struct mem_cgroup *memcg)
{
	// No-op: we don't maintain custom eviction lists
}

bool BPF_STRUCT_OPS(admit_hook_admit_folio, struct cache_ext_admission_ctx *admission_ctx)
{
	__u64 pid_tgid = bpf_get_current_pid_tgid();
	__u32 tid = pid_tgid & 0xffffffff;
	bool result;
#if !BYPASS_ALL
	struct read_key key;
	struct read_state *state;
	struct read_state new_state;
	bool sequential = false;
#endif
	
	__u8 *should_bypass = bpf_map_lookup_elem(&bypassed_tids, &tid);
	
	if (!should_bypass) {
		result = false; // Use page cache normally
		goto out;
	}

#if BYPASS_ALL
	if (admission_ctx->size >= BYPASS_MIN_SIZE)
		result = true;  // Bypass page cache for compaction reads
	else
		result = false; // Use page cache normally
#else
	key.ino = admission_ctx->ino;
	key.tid = tid;
	key.pad = 0;

	state = bpf_map_lookup_elem(&last_reads, &key);
	if (state) {
		__u64 expected = state->offset + state->size;
		if (admission_ctx->offset >= expected &&
		    admission_ctx->offset - expected <= SEQ_TOLERANCE)
			sequential = true;
	}

	new_state.offset = admission_ctx->offset;
	new_state.size = admission_ctx->size;
	bpf_map_update_elem(&last_reads, &key, &new_state, BPF_ANY);

	if (admission_ctx->size >= BYPASS_MIN_SIZE && sequential)
		result = true;  // Bypass page cache for sequential reads
	else
		result = false; // Use page cache normally
#endif

#ifdef BPF_DEBUG
	__u32 key = result ? 0 : 1;
	__u64 *count = bpf_map_lookup_elem(&admission_stats, &key);
	if (count) {
		__sync_fetch_and_add(count, 1);
	}
#endif

	out:
	return result;
}

SEC(".struct_ops.link")
struct cache_ext_ops admit_hook_ops = {
	.init = (void *)admit_hook_init,
	.evict_folios = (void *)admit_hook_evict_folios,
	.admit_folio = (void *)admit_hook_admit_folio,
};
