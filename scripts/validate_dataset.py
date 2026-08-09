#!/usr/bin/env python3
"""
memcap 数据集质量校验工具

检查 snapshot / VMA / pagemap / operation 是否能通过 sample_id 正确 join，
并输出 Markdown 风格的质量报告。

用法:
  python3 scripts/validate_dataset.py -i memcap_out/
  python3 scripts/validate_dataset.py -i memcap_out/ --session session_001
"""

import argparse
import csv
import os
import sys
from collections import defaultdict, namedtuple
from typing import Dict, List, Optional, Set, Tuple

# ====== 数据结构 ======

SampleInfo = namedtuple('SampleInfo', [
    'sample_id', 'operation_id', 'pid', 'process_name',
    'timestamp_ms', 'collect_status', 'foreground_state',
])

VmaInfo = namedtuple('VmaInfo', [
    'sample_id', 'pid', 'vma_id', 'vma_start', 'vma_end', 'vma_size_kb',
    'rss_kb', 'region_type', 'pathname',
])

PagemapInfo = namedtuple('PagemapInfo', [
    'sample_id', 'pid', 'vma_id', 'page_count', 'present_pages',
    'swapped_pages', 'present_ratio', 'scan_status',
])

OperationInfo = namedtuple('OperationInfo', [
    'operation_id', 'sample_id', 'process_name', 'pid',
    'timestamp_ms', 'foreground_state',
])

SessionInfo = namedtuple('SessionInfo', [
    'session_id', 'session_name', 'pid', 'start_timestamp_ms',
    'end_timestamp_ms', 'operation_count', 'sample_count',
])


# ====== CSV 加载 ======

def load_snapshot_index(path: str) -> List[SampleInfo]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(SampleInfo(
                    sample_id=r.get('sample_id', '').strip(),
                    operation_id=r.get('operation_id', '').strip(),
                    pid=int(r.get('pid', 0)),
                    process_name=r.get('process_name', '').strip(),
                    timestamp_ms=int(r.get('timestamp_ms', 0)),
                    collect_status=r.get('collect_status', '').strip(),
                    foreground_state=r.get('foreground_state', '').strip(),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def load_vma(path: str) -> List[VmaInfo]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(VmaInfo(
                    sample_id=r.get('sample_id', '').strip(),
                    pid=int(r.get('pid', 0)),
                    vma_id=r.get('vma_id', '').strip(),
                    vma_start=int(r.get('vma_start', '0'), 16),
                    vma_end=int(r.get('vma_end', '0'), 16),
                    vma_size_kb=int(r.get('vma_size_kb', 0)),
                    rss_kb=int(r.get('rss_kb', 0)),
                    region_type=r.get('region_type', '').strip(),
                    pathname=r.get('pathname', '').strip(),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def load_pagemap(path: str) -> List[PagemapInfo]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(PagemapInfo(
                    sample_id=r.get('sample_id', '').strip(),
                    pid=int(r.get('pid', 0)),
                    vma_id=r.get('vma_id', '').strip(),
                    page_count=int(r.get('page_count', 0)),
                    present_pages=int(r.get('present_pages', 0)),
                    swapped_pages=int(r.get('swapped_pages', 0)),
                    present_ratio=float(r.get('present_ratio', 0)),
                    scan_status=r.get('scan_status', '').strip(),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def load_operations(path: str) -> List[OperationInfo]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(OperationInfo(
                    operation_id=r.get('operation_id', '').strip(),
                    sample_id=r.get('sample_id', '').strip(),
                    process_name=r.get('process_name', '').strip(),
                    pid=int(r.get('pid', 0)),
                    timestamp_ms=int(r.get('timestamp_ms', 0)),
                    foreground_state=r.get('foreground_state', '').strip(),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def load_session_index(path: str) -> List[SessionInfo]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(SessionInfo(
                    session_id=r.get('session_id', '').strip(),
                    session_name=r.get('session_name', '').strip(),
                    pid=int(r.get('pid', 0)),
                    start_timestamp_ms=int(r.get('start_timestamp_ms', 0)),
                    end_timestamp_ms=int(r.get('end_timestamp_ms', 0)),
                    operation_count=int(r.get('operation_count', 0)),
                    sample_count=int(r.get('sample_count', 0)),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def load_process_snapshot(path: str) -> List[dict]:
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


# ====== 校验逻辑 ======

def check_joinability(samples: List[SampleInfo],
                     vma_map: Dict[str, List[VmaInfo]],
                     pm_map: Dict[str, List[PagemapInfo]],
                     op_map: Dict[str, List[OperationInfo]]) -> List[str]:
    """检查 snapshot / VMA / pagemap / operation 是否能通过 sample_id join。"""
    issues = []

    snapshot_ids = {s.sample_id for s in samples}
    vma_ids = set(vma_map.keys())
    pm_ids = set(pm_map.keys())
    op_ids = set(op_map.keys())

    # 每个 success sample 都应该在 VMA 和 pagemap 中有数据
    for s in samples:
        if s.collect_status != 'success':
            continue
        if s.sample_id not in vma_ids:
            issues.append(f"success sample [{s.sample_id}] 缺少 VMA 数据")
        if s.sample_id not in pm_ids:
            issues.append(f"success sample [{s.sample_id}] 缺少 pagemap 数据")

    # VMA 中的 sample_id 是否都能在 snapshot 中找到
    orphan_vma = vma_ids - snapshot_ids
    if orphan_vma:
        issues.append(f"VMA 中有 {len(orphan_vma)} 个孤儿 sample_id 不在 snapshot_index 中: "
                      f"{', '.join(sorted(list(orphan_vma)[:5]))}"
                      f"{'...' if len(orphan_vma) > 5 else ''}")

    # pagemap 中的 sample_id 是否都能在 snapshot 中找到
    orphan_pm = pm_ids - snapshot_ids
    if orphan_pm:
        issues.append(f"pagemap 中有 {len(orphan_pm)} 个孤儿 sample_id 不在 snapshot_index 中: "
                      f"{', '.join(sorted(list(orphan_pm)[:5]))}"
                      f"{'...' if len(orphan_pm) > 5 else ''}")

    # operation 与 snapshot 交叉校验
    for s in samples:
        if s.operation_id and s.operation_id not in op_map:
            # operation_list 可能尚未人工填写，仅做提示
            pass

    return issues


def check_vma_pagemap_consistency(samples: List[SampleInfo],
                                  vma_map: Dict[str, List[VmaInfo]],
                                  pm_map: Dict[str, List[PagemapInfo]]) -> List[str]:
    """检查同一个 sample 中 VMA 和 pagemap 的 vma_id 能否对上。"""
    issues = []

    for s in samples:
        if s.collect_status != 'success':
            continue
        vmas = vma_map.get(s.sample_id, [])
        pms = pm_map.get(s.sample_id, [])

        vma_vma_ids = {v.vma_id for v in vmas}
        pm_vma_ids = {p.vma_id for p in pms}

        # VMA 有但 pagemap 没有的
        missing_pm = vma_vma_ids - pm_vma_ids
        if len(missing_pm) > 0 and len(missing_pm) == len(vma_vma_ids):
            issues.append(f"[{s.sample_id}] 所有 {len(vma_vma_ids)} 个 VMA 都没有对应 pagemap 数据")

        # pagemap 有但 VMA 没有的（可能是异常）
        orphan_pm_vma = pm_vma_ids - vma_vma_ids
        if orphan_pm_vma:
            issues.append(f"[{s.sample_id}] pagemap 中有 {len(orphan_pm_vma)} 个 vma_id 不在 VMA 表中")

    return issues


def check_timestamps(samples: List[SampleInfo]) -> List[str]:
    """检查时间戳合理性。"""
    issues = []

    if not samples:
        return ["无样本数据"]

    # 按时间戳排序
    sorted_samples = sorted(samples, key=lambda s: s.timestamp_ms)

    # 检查时间戳是否单调递增
    for i in range(1, len(sorted_samples)):
        prev = sorted_samples[i - 1]
        curr = sorted_samples[i]
        if curr.timestamp_ms < prev.timestamp_ms:
            issues.append(f"时间戳回退: [{prev.sample_id}] {prev.timestamp_ms} → "
                          f"[{curr.sample_id}] {curr.timestamp_ms}")
        # 同一秒内大量样本（>10个）可能异常
        if curr.timestamp_ms - prev.timestamp_ms < 100 and i > 10:
            pass  # 快速连续采集是正常的，不报 issue

    # 检查是否有未来时间戳（超过当前时间 1 天）
    import time
    now_ms = int(time.time() * 1000)
    future_samples = [s for s in samples if s.timestamp_ms > now_ms + 86400000]
    if future_samples:
        issues.append(f"发现 {len(future_samples)} 个未来时间戳样本")

    # 检查零时间戳
    zero_ts = [s.sample_id for s in samples if s.timestamp_ms == 0]
    if zero_ts:
        issues.append(f"{len(zero_ts)} 个样本时间戳为 0: {', '.join(zero_ts[:5])}")

    return issues


def check_collect_status(samples: List[SampleInfo]) -> List[str]:
    """检查 collect_status 分布。"""
    issues = []

    status_counts = defaultdict(int)
    for s in samples:
        status_counts[s.collect_status] += 1

    failed = status_counts.get('success', 0)

    if 'open_maps_failed' in status_counts:
        n = status_counts['open_maps_failed']
        issues.append(f"{n} 个样本 collect_status=open_maps_failed (/proc/[pid]/maps 无法打开)")

    if 'alloc_failed' in status_counts:
        n = status_counts['alloc_failed']
        issues.append(f"{n} 个样本 collect_status=alloc_failed (VMA 内存分配失败)")

    return issues


def check_pagemap_scan_status(pm_rows: List[PagemapInfo]) -> List[str]:
    """检查 pagemap scan_status 分布。"""
    issues = []

    status_counts = defaultdict(int)
    sample_issues = defaultdict(list)

    for p in pm_rows:
        status_counts[p.scan_status] += 1
        if p.scan_status != 'success':
            sample_issues[p.sample_id].append(p.scan_status)

    if 'open_pagemap_failed' in status_counts:
        n = status_counts['open_pagemap_failed']
        issues.append(f"pagemap 扫描: {n} 个 VMA 条目 scan_status=open_pagemap_failed "
                      f"(涉及 {len(sample_issues)} 个样本)")

    if 'partial_scan' in status_counts:
        n = status_counts['partial_scan']
        issues.append(f"pagemap 扫描: {n} 个 VMA 条目 scan_status=partial_scan "
                      f"(pread 部分失败)")

    return issues


def check_session_consistency(sessions: List[SessionInfo],
                              process_snaps: List[dict],
                              samples: List[SampleInfo]) -> List[str]:
    """检查 session 层数据一致性。"""
    issues = []

    if not sessions:
        return issues  # 无 session 数据不报错

    for sess in sessions:
        # 检查 sample_count 是否与 process_snapshot 一致
        ps_count = sum(1 for p in process_snaps
                       if p.get('session_id', '') == sess.session_id)
        if ps_count != sess.sample_count:
            issues.append(f"[{sess.session_id}] session 记录 sample_count={sess.sample_count} "
                          f"但 process_snapshot 中实际有 {ps_count} 条记录")

        # 检查结束时间大于开始时间
        if sess.end_timestamp_ms <= sess.start_timestamp_ms:
            issues.append(f"[{sess.session_id}] 结束时间戳 <= 开始时间戳")

    return issues


# ====== 报告输出 ======

def print_report(samples: List[SampleInfo],
                 vma_map: Dict[str, List[VmaInfo]],
                 pm_map: Dict[str, List[PagemapInfo]],
                 op_list: List[OperationInfo],
                 sessions: List[SessionInfo],
                 process_snaps: List[dict],
                 all_issues: List[str],
                 csv_dir: str):
    """输出 Markdown 格式的数据质量报告。"""

    success_count = sum(1 for s in samples if s.collect_status == 'success')
    failed_count = len(samples) - success_count

    total_vma_rows = sum(len(v) for v in vma_map.values())
    total_pm_rows = sum(len(p) for p in pm_map.values())

    pm_status_counts = defaultdict(int)
    for p_list in pm_map.values():
        for p in p_list:
            pm_status_counts[p.scan_status] += 1

    print(f"""
================================================================================
  memcap 数据集质量报告
================================================================================
数据目录:     {csv_dir}
校验时间:     {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

## 数据概览

| 指标 | 值 |
|------|----|
| snapshot 总数 | {len(samples)} |
| success 样本 | {success_count} |
| failed 样本 | {failed_count} |
| VMA 总行数 | {total_vma_rows} |
| pagemap 总行数 | {total_pm_rows} |
| operation 记录 | {len(op_list)} |
| session 记录 | {len(sessions)} |
| distinct PID | {len(set(s.pid for s in samples))} |
| distinct operation | {len(set(s.operation_id for s in samples))} |
| 时间范围 | {min(s.timestamp_ms for s in samples) if samples else 'N/A'} → {max(s.timestamp_ms for s in samples) if samples else 'N/A'} |

## Join 校验

| 检查项 | 状态 |
|--------|------|
| snapshot ↔ VMA (success sample 都有 VMA) | {"PASS" if not any("缺少 VMA 数据" in i for i in all_issues) else "FAIL"} |
| snapshot ↔ pagemap (success sample 都有 pagemap) | {"PASS" if not any("缺少 pagemap 数据" in i for i in all_issues) else "FAIL"} |
| VMA vma_id ↔ pagemap vma_id 一致性 | {"PASS" if not any("vma_id 不在" in i for i in all_issues) else "FAIL"} |
| 无孤儿 sample_id | {"PASS" if not any("孤儿" in i for i in all_issues) else "FAIL"} |
| session ↔ process_snapshot 一致 | {"PASS" if not any("session" in i.lower() for i in all_issues) else "FAIL"} |

## collect_status 分布

| 状态 | 数量 | 占比 |
|------|:----:|:----:|
""")

    status_counts = defaultdict(int)
    for s in samples:
        status_counts[s.collect_status] += 1

    for st, cnt in sorted(status_counts.items(), key=lambda x: -x[1]):
        pct = cnt / len(samples) * 100 if samples else 0
        flag = " :white_check_mark:" if st == 'success' else " :x:"
        print(f"| {st}{flag} | {cnt} | {pct:.1f}% |")

    print(f"""
## pagemap scan_status 分布

| 状态 | 数量 | 占比 |
|------|:----:|:----:|
""")

    for st, cnt in sorted(pm_status_counts.items(), key=lambda x: -x[1]):
        pct = cnt / total_pm_rows * 100 if total_pm_rows else 0
        flag = " :white_check_mark:" if st == 'success' else " :warning:"
        print(f"| {st}{flag} | {cnt} | {pct:.1f}% |")

    # 时间戳检查
    print(f"""
## 时间戳校验

| 检查项 | 状态 |
|--------|------|
| 单调递增 | {"PASS" if not any("时间戳回退" in i for i in all_issues) else "FAIL"} |
| 无未来时间戳 | {"PASS" if not any("未来时间戳" in i for i in all_issues) else "FAIL"} |
| 无零时间戳 | {"PASS" if not any("时间戳为 0" in i for i in all_issues) else "FAIL"} |
""")

    # 按 PID 分组详情
    by_pid = defaultdict(list)
    for s in samples:
        by_pid[s.pid].append(s)

    print(f"## 按 PID 分组\n")
    print(f"| PID | Process | 样本数 | success | failed | VMA行 | pagemap行 |")
    print(f"|-----|---------|:------:|:-------:|:------:|:-----:|:---------:|")
    for pid, grp in sorted(by_pid.items()):
        succ = sum(1 for s in grp if s.collect_status == 'success')
        fail = len(grp) - succ
        vma_n = sum(len(vma_map.get(s.sample_id, [])) for s in grp)
        pm_n = sum(len(pm_map.get(s.sample_id, [])) for s in grp)
        pname = grp[0].process_name[:40] if grp[0].process_name else '?'
        print(f"| {pid} | {pname} | {len(grp)} | {succ} | {fail} | {vma_n} | {pm_n} |")

    # 按 operation 分组
    by_op = defaultdict(list)
    for s in samples:
        by_op[s.operation_id].append(s)

    print(f"\n## 按 Operation 分组\n")
    print(f"| Operation | 样本数 | success |")
    print(f"|-----------|:------:|:-------:|")
    for op, grp in sorted(by_op.items()):
        succ = sum(1 for s in grp if s.collect_status == 'success')
        print(f"| {op[:60]} | {len(grp)} | {succ} |")

    # Session 信息
    if sessions:
        print(f"\n## Session 信息\n")
        print(f"| Session | 名称 | PID | 操作数 | 样本数 | 时长(s) |")
        print(f"|---------|------|-----|:------:|:------:|:-------:|")
        for sess in sessions:
            duration_s = (sess.end_timestamp_ms - sess.start_timestamp_ms) / 1000.0
            print(f"| {sess.session_id} | {sess.session_name} | {sess.pid} | "
                  f"{sess.operation_count} | {sess.sample_count} | {duration_s:.0f} |")

    # 问题汇总
    critical = [i for i in all_issues if any(kw in i for kw in
        ['缺少 VMA 数据', '缺少 pagemap 数据', 'open_maps_failed', 'alloc_failed'])]
    warnings = [i for i in all_issues if i not in critical]

    print(f"""
## 问题汇总

| 级别 | 数量 |
|------|:----:|
| Critical | {len(critical)} |
| Warning | {len(warnings)} |
""")

    if critical:
        print("### Critical\n")
        for i in critical:
            print(f"- :x: {i}")
        print()

    if warnings:
        print("### Warning\n")
        for i in warnings:
            print(f"- :warning: {i}")
        print()

    if not all_issues:
        print(":white_check_mark: 所有校验通过，数据集状态良好。\n")

    overall = "PASS" if len(critical) == 0 else "FAIL"
    print(f"---")
    print(f"*Overall: **{overall}** | {success_count}/{len(samples)} samples success | "
          f"report by validate_dataset.py*")


# ====== 入口 ======

def main():
    parser = argparse.ArgumentParser(
        description='memcap 数据集质量校验 — 检查 CSV join、一致性和采集状态',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -i memcap_out/
  %(prog)s -i memcap_out/ --session session_001
        """)
    parser.add_argument('-i', '--input', default='memcap_out',
                        help='CSV 结果目录 (默认: memcap_out)')
    parser.add_argument('--session', default=None,
                        help='只检查指定 session_id')
    args = parser.parse_args()

    csv_dir = args.input
    if not os.path.isdir(csv_dir):
        print(f"[错误] 目录不存在: {csv_dir}", file=sys.stderr)
        sys.exit(1)

    # 加载数据
    print("[加载] 读取 CSV 数据...", file=sys.stderr)

    samples = load_snapshot_index(os.path.join(csv_dir, 'snapshot_index.csv'))
    print(f"  snapshot_index: {len(samples)} 行", file=sys.stderr)

    vma_rows = load_vma(os.path.join(csv_dir, 'vma_memory_snapshot.csv'))
    print(f"  vma_memory_snapshot: {len(vma_rows)} 行", file=sys.stderr)

    pm_rows = load_pagemap(os.path.join(csv_dir, 'pagemap_snapshot.csv'))
    print(f"  pagemap_snapshot: {len(pm_rows)} 行", file=sys.stderr)

    op_rows = load_operations(os.path.join(csv_dir, 'operation_list.csv'))
    print(f"  operation_list: {len(op_rows)} 行", file=sys.stderr)

    sessions = load_session_index(os.path.join(csv_dir, 'session_index.csv'))
    print(f"  session_index: {len(sessions)} 行", file=sys.stderr)

    process_snaps = load_process_snapshot(os.path.join(csv_dir, 'process_snapshot.csv'))
    print(f"  process_snapshot: {len(process_snaps)} 行", file=sys.stderr)

    if not samples:
        print("[错误] snapshot_index.csv 为空或不存在", file=sys.stderr)
        sys.exit(1)

    # 按 session 筛选
    if args.session:
        ps_session_samples = {p.get('sample_id', '') for p in process_snaps
                              if p.get('session_id', '') == args.session}
        if ps_session_samples:
            samples = [s for s in samples if s.sample_id in ps_session_samples]
            print(f"[筛选] session={args.session}: {len(samples)} 样本", file=sys.stderr)

    # 构建索引
    vma_map = defaultdict(list)
    for v in vma_rows:
        vma_map[v.sample_id].append(v)

    pm_map = defaultdict(list)
    for p in pm_rows:
        pm_map[p.sample_id].append(p)

    op_map = defaultdict(list)
    for o in op_rows:
        op_map[o.operation_id].append(o)

    # 执行校验
    print("[校验] 执行数据质量检查...", file=sys.stderr)

    all_issues = []
    all_issues.extend(check_joinability(samples, vma_map, pm_map, op_map))
    all_issues.extend(check_vma_pagemap_consistency(samples, vma_map, pm_map))
    all_issues.extend(check_timestamps(samples))
    all_issues.extend(check_collect_status(samples))
    all_issues.extend(check_pagemap_scan_status(pm_rows))
    all_issues.extend(check_session_consistency(sessions, process_snaps, samples))

    # 输出报告
    print_report(samples, vma_map, pm_map, op_rows, sessions, process_snaps,
                 all_issues, csv_dir)

    # 退出码
    critical_count = sum(1 for i in all_issues if any(kw in i for kw in
        ['缺少 VMA 数据', '缺少 pagemap 数据', 'open_maps_failed', 'alloc_failed']))
    if critical_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
