#!/usr/bin/env python3
import os, sys, ctypes, signal
from bcc import BPF

def get_cgroup_id(cgroup_path):
    if not os.path.exists(cgroup_path): return 0
    return os.stat(cgroup_path).st_ino

target_cgroup = sys.argv[1] if len(sys.argv) > 1 else ""
cgroup_id = get_cgroup_id(target_cgroup)
if cgroup_id == 0:
    print("错误：请提供有效的 Cgroup 路径"); sys.exit(1)

# 注意：C代码中的 { 和 } 都必须写成 {{ 和 }} 以兼容 python f-string
bpf_text = f"""
#define TRACER_PID {os.getpid()}
#define TARGET_CGROUP_ID {cgroup_id}ull
#include <linux/mm.h>
#include <linux/fs.h>
#include <linux/pagemap.h>
#include <linux/sched.h>

struct op_context_t {{
    u64 start_ts;
    u64 op_id;
    u32 op_type;
}};
BPF_HASH(op_ctx_map, u32, struct op_context_t);
BPF_HASH(monitored_inodes, u64, u8);

struct page_event_t {{
    u64 ts; u64 op_id; u64 ino; u64 offset; u64 file_size_pages; u64 op_duration_ns;
    u32 pid; u32 tid; u32 event_type; u32 op_type; u32 major; u32 minor; char comm[16];
}} __attribute__((packed));

BPF_PERF_OUTPUT(events);

static inline bool is_target() {{
    u64 ptid = bpf_get_current_pid_tgid();
    if ((ptid >> 32) == TRACER_PID) return false;
    return bpf_get_current_cgroup_id() == TARGET_CGROUP_ID;
}}

static inline bool get_folio_info(struct folio *folio, struct address_space *mapped_as, u64 *ino, u64 *idx, u32 *maj, u32 *min, u64 *fsize) {{
    unsigned long m_val = (unsigned long)mapped_as;
    if (!m_val) bpf_probe_read_kernel(&m_val, sizeof(m_val), &folio->mapping);
    if (m_val & 1) return false;
    struct address_space *m = (struct address_space *)(m_val & ~3UL);
    if (!m) return false;
    struct inode *h = NULL; bpf_probe_read_kernel(&h, sizeof(h), &m->host);
    if (!h) return false;
    bpf_probe_read_kernel(ino, sizeof(*ino), &h->i_ino);
    bpf_probe_read_kernel(idx, sizeof(*idx), &folio->index);
    struct super_block *sb = NULL; bpf_probe_read_kernel(&sb, sizeof(sb), &h->i_sb);
    if (sb) {{
        u32 dev = 0; bpf_probe_read_kernel(&dev, sizeof(dev), &sb->s_dev);
        *maj = dev >> 20; *min = dev & ((1U << 20) - 1);
    }}
    loff_t isize = 0; bpf_probe_read_kernel(&isize, sizeof(isize), &h->i_size);
    *fsize = (isize + 4095) / 4096;
    return true;
}}

static inline void submit_ev(struct pt_regs *ctx, struct folio *folio, u32 type) {{
    u64 ino = 0, offset = 0, file_size_pages = 0;
    u32 major = 0, minor = 0;
    
    if (!get_folio_info(folio, NULL, &ino, &offset, &major, &minor, &file_size_pages)) return;

    bool target_proc = is_target();
    u8 *is_monitored = monitored_inodes.lookup(&ino);

    // 如果不是目标进程，且这个文件之前也没被目标进程摸过，就丢弃
    if (!target_proc && !is_monitored) return;

    // 如果是目标进程摸了一个文件，把该 Inode 加入长期监视名单
    if (target_proc) {{
        u8 val = 1;
        monitored_inodes.update(&ino, &val);
    }}
    
    u64 ptid = bpf_get_current_pid_tgid();
    u32 tid = (u32)ptid;
    struct page_event_t e = {{}};
    e.ino = ino; e.offset = offset; e.major = major; e.minor = minor; e.file_size_pages = file_size_pages;
    e.ts = bpf_ktime_get_ns();
    e.pid = ptid >> 32;
    e.tid = tid;
    e.event_type = type;
    bpf_get_current_comm(&e.comm, sizeof(e.comm));

    // 检查是否有直接的操作上下文（如同步读写）
    struct op_context_t *ctx_op = op_ctx_map.lookup(&tid);
    if (ctx_op) {{
        e.op_id = ctx_op->op_id;
        e.op_type = ctx_op->op_type;
    }} else {{
        e.op_id = 0;
        e.op_type = 0; // 上下文无关的后台操作
    }}
    
    events.perf_submit(ctx, &e, sizeof(e));
}}

int kprobe__folio_mark_accessed(struct pt_regs *ctx, struct folio *folio) {{ submit_ev(ctx, folio, 0); return 0; }}
int kprobe__folio_add_lru(struct pt_regs *ctx, struct folio *folio) {{ submit_ev(ctx, folio, 1); return 0; }}
int kprobe__filemap_remove_folio(struct pt_regs *ctx, struct folio *folio) {{ submit_ev(ctx, folio, 2); return 0; }}

// 追踪读操作 (READ)
int kprobe__vfs_read(struct pt_regs *ctx) {{
    if (!is_target()) return 0;
    u32 tid = (u32)bpf_get_current_pid_tgid();
    struct op_context_t c = {{.start_ts = bpf_ktime_get_ns(), .op_type = 1}};
    c.op_id = c.start_ts;
    op_ctx_map.update(&tid, &c);
    return 0;
}}
int kretprobe__vfs_read(struct pt_regs *ctx) {{
    u32 tid = (u32)bpf_get_current_pid_tgid();
    struct op_context_t *c = op_ctx_map.lookup(&tid);
    if (!c) return 0;
    struct page_event_t e = {{.event_type = 3, .op_type = 1}};
    e.ts = bpf_ktime_get_ns(); e.op_id = c->op_id;
    e.op_duration_ns = e.ts - c->start_ts;
    e.pid = bpf_get_current_pid_tgid() >> 32; e.tid = tid;
    bpf_get_current_comm(&e.comm, sizeof(e.comm));
    events.perf_submit(ctx, &e, sizeof(e));
    op_ctx_map.delete(&tid);
    return 0;
}}

// 追踪写操作 (WRITE)
int kprobe__vfs_write(struct pt_regs *ctx) {{
    if (!is_target()) return 0;
    u32 tid = (u32)bpf_get_current_pid_tgid();
    struct op_context_t c = {{.start_ts = bpf_ktime_get_ns(), .op_type = 2}};
    c.op_id = c.start_ts;
    op_ctx_map.update(&tid, &c);
    return 0;
}}
int kretprobe__vfs_write(struct pt_regs *ctx) {{
    u32 tid = (u32)bpf_get_current_pid_tgid();
    struct op_context_t *c = op_ctx_map.lookup(&tid);
    if (!c) return 0;
    struct page_event_t e = {{.event_type = 3, .op_type = 2}};
    e.ts = bpf_ktime_get_ns(); e.op_id = c->op_id;
    e.op_duration_ns = e.ts - c->start_ts;
    e.pid = bpf_get_current_pid_tgid() >> 32; e.tid = tid;
    bpf_get_current_comm(&e.comm, sizeof(e.comm));
    events.perf_submit(ctx, &e, sizeof(e));
    op_ctx_map.delete(&tid);
    return 0;
}}
"""
b = BPF(text=bpf_text)
f = open("raw_trace.bin", "wb")
def print_event(cpu, data, size): f.write(ctypes.string_at(data, 88))
b["events"].open_perf_buffer(print_event, page_cnt=8192)
print(f"追踪开启 (目标 Cgroup: {target_cgroup}) - 已支持捕捉后台 kswapd 等内核线程")
try:
    while True: b.perf_buffer_poll()
except KeyboardInterrupt:
    f.close(); print("\n结束。")
