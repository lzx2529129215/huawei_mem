#!/usr/bin/env python3
import os
import sys
import ctypes
import signal
from bcc import BPF

bpf_text = """
#include <linux/kconfig.h>
#include <linux/mm.h>
#include <linux/fs.h>
#include <linux/pagemap.h>
#include <linux/sched.h>

struct op_context_t {
    u64 start_ts;
    u64 op_id;       
    u32 op_type;     
    u32 pad;         
};
BPF_HASH(op_ctx_map, u32, struct op_context_t);

struct page_event_t {
    u64 ts;
    u64 op_id;             
    u64 ino;
    u64 offset;
    u64 file_size_pages;
    u64 op_duration_ns;
    u32 pid;
    u32 tid;
    u32 event_type;        
    u32 op_type;           
    u32 major;
    u32 minor;
    char comm[16];
} __attribute__((packed));

BPF_PERF_OUTPUT(events);

static inline bool get_folio_info(struct folio *folio, struct address_space *mapped_as, u64 *inode_num, u64 *index, u32 *major, u32 *minor, u64 *file_size_pages) {
    unsigned long mapping_val = (unsigned long)mapped_as;
    
    // 如果未显式传入 mapping，则从 folio 中读取
    if (!mapping_val) {
        bpf_probe_read_kernel(&mapping_val, sizeof(mapping_val), &folio->mapping);
    }
    
    // 【关键修复】: 过滤匿名页 (Anonymous Pages)
    // Linux 中如果是进程自己 malloc 的内存，mapping 最低位会是 1 (PAGE_MAPPING_ANON)
    // 只有正经的文件页，我们才需要提取
    if (mapping_val & 1) return false;
    
    // 清除低位的系统 flag
    struct address_space *mapping = (struct address_space *)(mapping_val & ~3UL);
    if (!mapping) return false;

    struct inode *host = NULL;
    bpf_probe_read_kernel(&host, sizeof(host), &mapping->host);
    if (!host) return false;
    
    bpf_probe_read_kernel(inode_num, sizeof(*inode_num), &host->i_ino);
    if (*inode_num == 0) return false;
    
    bpf_probe_read_kernel(index, sizeof(*index), &folio->index);
    
    struct super_block *sb = NULL;
    bpf_probe_read_kernel(&sb, sizeof(sb), &host->i_sb);
    if (sb) {
        u32 dev = 0;
        bpf_probe_read_kernel(&dev, sizeof(dev), &sb->s_dev);
        *major = dev >> 20;               
        *minor = dev & ((1U << 20) - 1);  
    } else {
        *major = 0;
        *minor = 0;
    }

    loff_t i_size = 0;
    bpf_probe_read_kernel(&i_size, sizeof(i_size), &host->i_size);
    *file_size_pages = (i_size + 4095) / 4096;

    return true;
}

static inline void submit_page_event(struct pt_regs *ctx, struct folio *folio, struct address_space *mapping, u32 event_type) {
    u64 pid_tgid = bpf_get_current_pid_tgid();
    u32 pid = pid_tgid >> 32;
    u32 tid = pid_tgid;

    if (pid == TRACER_PID) return;

    u64 inode_num = 0, page_idx = 0, file_size_pages = 0;
    u32 major = 0, minor = 0;
    
    if (!get_folio_info(folio, mapping, &inode_num, &page_idx, &major, &minor, &file_size_pages)) return;
        
    struct page_event_t e = {};
    e.ts = bpf_ktime_get_ns();
    e.pid = pid;
    e.tid = tid;
    e.event_type = event_type;
    e.ino = inode_num;
    e.offset = page_idx;
    e.major = major;
    e.minor = minor;
    e.file_size_pages = file_size_pages;
    bpf_get_current_comm(&e.comm, sizeof(e.comm));

    struct op_context_t *ctx_op = op_ctx_map.lookup(&tid);
    if (ctx_op) {
        e.op_id = ctx_op->op_id;
        e.op_type = ctx_op->op_type;
    } else {
        e.op_id = 0;
        e.op_type = 0;
    }

    events.perf_submit(ctx, &e, sizeof(e));
}

// 0: ACCESS (访问)
int kprobe__folio_mark_accessed(struct pt_regs *ctx, struct folio *folio) { 
    submit_page_event(ctx, folio, NULL, 0); 
    return 0; 
}

// 1: INSERT (插入)
// 【关键修复】: 放弃使用容易被内联的 filemap_add_folio，改用必定被调用的 folio_add_lru
int kprobe__folio_add_lru(struct pt_regs *ctx, struct folio *folio) { 
    submit_page_event(ctx, folio, NULL, 1); 
    return 0; 
}

// 2: EVICT (驱逐)
int kprobe__filemap_remove_folio(struct pt_regs *ctx, struct folio *folio) { 
    submit_page_event(ctx, folio, NULL, 2); 
    return 0; 
}

static inline int trace_op_entry(u32 op_type) {
    u64 pid_tgid = bpf_get_current_pid_tgid();
    u32 pid = pid_tgid >> 32;
    u32 tid = pid_tgid;
    if (pid == TRACER_PID) return 0;

    struct op_context_t ctx = {};
    ctx.start_ts = bpf_ktime_get_ns();
    ctx.op_id = ctx.start_ts; 
    ctx.op_type = op_type;
    op_ctx_map.update(&tid, &ctx);
    return 0;
}

static inline int trace_op_return(struct pt_regs *ctx) {
    u64 pid_tgid = bpf_get_current_pid_tgid();
    u32 pid = pid_tgid >> 32;
    u32 tid = pid_tgid;
    if (pid == TRACER_PID) return 0;

    struct op_context_t *ctx_op = op_ctx_map.lookup(&tid);
    if (!ctx_op) return 0;

    struct page_event_t e = {};
    e.ts = bpf_ktime_get_ns();
    e.op_id = ctx_op->op_id;
    e.pid = pid;
    e.tid = tid;
    e.event_type = 3;  // OP_DONE
    e.op_type = ctx_op->op_type;
    e.op_duration_ns = e.ts - ctx_op->start_ts;
    bpf_get_current_comm(&e.comm, sizeof(e.comm));

    events.perf_submit(ctx, &e, sizeof(e));
    op_ctx_map.delete(&tid);
    return 0;
}

int kprobe__vfs_read(struct pt_regs *ctx) { return trace_op_entry(1); } 
int kretprobe__vfs_read(struct pt_regs *ctx) { return trace_op_return(ctx); }
int kprobe__vfs_write(struct pt_regs *ctx) { return trace_op_entry(2); } 
int kretprobe__vfs_write(struct pt_regs *ctx) { return trace_op_return(ctx); }
"""

my_pid = os.getpid()
bpf_text = f"#define TRACER_PID {my_pid}\n" + bpf_text

print("[1] 正在编译原生 eBPF 模块...")
b = BPF(text=bpf_text)

bin_file_path = "raw_trace.bin"
bin_file = open(bin_file_path, "wb")
print(f"[2] 原始数据将以高吞吐模式保存至 {bin_file_path}")
print("开始追踪页面缓存状态，请运行你的工作负载 (按 Ctrl+C 停止并保存)...")

is_exiting = False
def signal_handler(sig, frame):
    global is_exiting
    is_exiting = True
    print("\n[3] 接收到退出信号，正在关闭追踪器...")
signal.signal(signal.SIGINT, signal_handler)

EVENT_STRUCT_SIZE = 88
def handle_raw_event(cpu, data, size):
    if is_exiting: return
    if size >= EVENT_STRUCT_SIZE:
        bin_file.write(ctypes.string_at(data, EVENT_STRUCT_SIZE))

b["events"].open_perf_buffer(handle_raw_event, page_cnt=1024)

while not is_exiting:
    try:
        b.perf_buffer_poll(timeout=100)
    except KeyboardInterrupt:
        is_exiting = True

bin_file.flush()
bin_file.close()
print("保存成功。")
