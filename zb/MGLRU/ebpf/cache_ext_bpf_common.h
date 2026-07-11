#ifndef __CACHE_EXT_BPF_COMMON_H
#define __CACHE_EXT_BPF_COMMON_H

#define CACHE_EXT_HIST_LEN 4

#if !defined(CACHE_EXT_SKIP_CTX) && !defined(__VMLINUX_H__)
struct cache_ext_bpf_ctx {
	unsigned short app_id;
	unsigned int dev_major;
	unsigned int dev_minor;
	unsigned long long ino;
	unsigned long long index_start;
	unsigned long long index_end;
};
#endif

#ifndef __VMLINUX_H__
struct cache_ext_bpf_cycle_ctx {
	unsigned short app_id;
	unsigned long long cycle_seq;
};
#endif

struct cache_ext_hist_val {
	unsigned short ops[CACHE_EXT_HIST_LEN];
	unsigned char len;
};

struct cache_ext_markov_key {
	unsigned short app_id;
	unsigned short ctx[CACHE_EXT_HIST_LEN];
};

struct cache_ext_markov_val {
	unsigned short next_op;
	unsigned int count;
};

struct cache_ext_profile_key {
	unsigned short app_id;
	unsigned short op_id;
	unsigned int dev_major;
	unsigned int dev_minor;
	unsigned long long ino;
};

struct cache_ext_profile_val {
	unsigned long long index_start;
	unsigned long long index_end;
	unsigned short priority;
};

#endif