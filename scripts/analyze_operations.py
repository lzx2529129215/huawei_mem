#!/usr/bin/env python3
"""
操作级内存持久性分析工具

核心问题：在不同操作之间，哪些地址空间（VMA）持续驻留物理内存？
→ 这些区域不应该被杀死，因为后续操作还会使用。
→ 仅在单个操作中出现的区域可以安全回收。

分析维度：
  1. 跨操作持久性 — VMA 在几个操作中持续有物理驻留
  2. 操作独有性   — VMA 只在某个操作中出现
  3. 物理贡献度   — VMA 的 RSS/present_pages 占比
  4. 操作转换矩阵 — op_A → op_B 的共享/独有 VMA

输出：
  - future_need_label.csv  标注 should_keep + 理由
  - 终端 Markdown 报告
  - (可选) HTML 可视化报告

用法:
  python3 scripts/analyze_operations.py -i memcap_out/
  python3 scripts/analyze_operations.py -i memcap_out/ --threshold 0.1 --min-rss 100
"""

import argparse
import csv
import os
import sys
from collections import defaultdict, namedtuple
from typing import Dict, List, Optional, Set, Tuple

# ====== 数据结构 ======

VmaRow = namedtuple('VmaRow', [
    'sample_id', 'operation_id', 'pid', 'vma_id', 'vma_start', 'vma_end',
    'vma_size_kb', 'perms', 'pathname', 'region_type',
    'rss_kb', 'pss_kb', 'referenced_kb', 'anonymous_kb', 'swap_kb', 'vm_flags',
])

PagemapRow = namedtuple('PagemapRow', [
    'sample_id', 'vma_id', 'page_count', 'present_pages', 'swapped_pages',
    'file_or_shared_pages', 'exclusive_pages', 'present_ratio', 'scan_status',
])

SnapshotMeta = namedtuple('SnapshotMeta', [
    'sample_id', 'operation_id', 'pid', 'process_name',
    'timestamp_ms', 'foreground_state',
])


# ====== CSV 解析 ======

def parse_snapshot_index(csv_dir: str) -> List[SnapshotMeta]:
    path = os.path.join(csv_dir, 'snapshot_index.csv')
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            if r.get('collect_status', '') != 'success':
                continue
            rows.append(SnapshotMeta(
                sample_id=r['sample_id'],
                operation_id=r['operation_id'],
                pid=int(r.get('pid', 0)),
                process_name=r.get('process_name', '').strip(),
                timestamp_ms=int(r.get('timestamp_ms', 0)),
                foreground_state=r.get('foreground_state', ''),
            ))
    return rows


def parse_vma_csv(csv_dir: str) -> List[VmaRow]:
    path = os.path.join(csv_dir, 'vma_memory_snapshot.csv')
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(VmaRow(
                    sample_id=r['sample_id'],
                    operation_id=r['operation_id'],
                    pid=int(r.get('pid', 0)),
                    vma_id=r['vma_id'],
                    vma_start=int(r.get('vma_start', '0'), 16),
                    vma_end=int(r.get('vma_end', '0'), 16),
                    vma_size_kb=int(r.get('vma_size_kb', 0)),
                    perms=r.get('perms', ''),
                    pathname=r.get('pathname', ''),
                    region_type=r.get('region_type', ''),
                    rss_kb=int(r.get('rss_kb', 0)),
                    pss_kb=int(r.get('pss_kb', 0)),
                    referenced_kb=int(r.get('referenced_kb', 0)),
                    anonymous_kb=int(r.get('anonymous_kb', 0)),
                    swap_kb=int(r.get('swap_kb', 0)),
                    vm_flags=r.get('vm_flags', ''),
                ))
            except (ValueError, KeyError):
                continue
    return rows


def parse_pagemap_csv(csv_dir: str) -> List[PagemapRow]:
    path = os.path.join(csv_dir, 'pagemap_snapshot.csv')
    rows = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            try:
                rows.append(PagemapRow(
                    sample_id=r['sample_id'],
                    vma_id=r['vma_id'],
                    page_count=int(r.get('page_count', 0)),
                    present_pages=int(r.get('present_pages', 0)),
                    swapped_pages=int(r.get('swapped_pages', 0)),
                    file_or_shared_pages=int(r.get('file_or_shared_pages', 0)),
                    exclusive_pages=int(r.get('exclusive_pages', 0)),
                    present_ratio=float(r.get('present_ratio', 0)),
                    scan_status=r.get('scan_status', ''),
                ))
            except (ValueError, KeyError):
                continue
    return rows


# ====== 核心分析 ======

def make_fuzzy_key(vma: VmaRow) -> str:
    """语义匹配键 — 处理 PID 变化和 ASLR。"""
    pn = vma.pathname.strip()
    # 对于匿名区域 [anon:xxx]，pathname 本身就足够区分
    # 对于文件映射，使用 pathname + perms
    if pn.startswith('[anon:') or pn in ('[heap]', '[stack]', '[vdso]', '[vvar]'):
        return f"{pn}|{vma.perms}"
    return f"{pn}|{vma.region_type}|{vma.perms}"


def analyze_operations(
    snapshots: List[SnapshotMeta],
    vma_rows: List[VmaRow],
    pm_index: Dict[Tuple[str, str], PagemapRow],
    threshold: float,
    min_rss_kb: int,
) -> dict:
    """
    核心分析：按操作分组，计算每个 VMA 的跨操作持久性。

    返回结构:
      {
        'operations': [operation_id ...],  # 按时间排序
        'op_order': {operation_id: index},
        'vma_analysis': [
          {
            'vma_key': str,
            'pathname': str,
            'region_type': str,
            'perms': str,
            'vma_size_kb': int,
            'present_in_ops': [op_id ...],  # 哪些操作中有物理驻留
            'absent_from_ops': [op_id ...],  # 哪些操作中没有
            'rss_per_op': {op_id: rss_kb},
            'present_ratio_per_op': {op_id: ratio},
            'persistence': float,  # 0-1, 有物理驻留的操作比例
            'should_keep': 'YES'|'NO'|'CONDITIONAL',
            'reason': str,
          }
        ],
        'op_transition_matrix': {(op_a, op_b): {shared: [vma_keys], only_a: [...], only_b: [...]}},
      }
    """
    # 按时间排序操作
    op_order = sorted(set(s.operation_id for s in snapshots),
                      key=lambda oid: min(s.timestamp_ms for s in snapshots if s.operation_id == oid))
    operations = op_order

    sample_to_op = {s.sample_id: s.operation_id for s in snapshots}
    op_samples = defaultdict(list)
    for s in snapshots:
        op_samples[s.operation_id].append(s.sample_id)

    # 筛选有足够物理内存的 VMA
    significant_vmas = [v for v in vma_rows
                        if v.sample_id in sample_to_op and v.rss_kb >= min_rss_kb]

    # 按 fuzzy key 分组
    vma_index = defaultdict(lambda: defaultdict(list))
    for v in significant_vmas:
        key = make_fuzzy_key(v)
        op = sample_to_op[v.sample_id]
        vma_index[key][op].append(v)

    n_ops = len(operations)
    vma_analyses = []

    # 操作转换矩阵
    transition_matrix = {}

    for key, op_groups in vma_index.items():
        rep = next(iter(op_groups[list(op_groups.keys())[0]]))
        if not rep:
            continue

        present_in = []
        absent_from = []
        rss_per_op = {}
        ratio_per_op = {}
        has_physical = 0

        for op in operations:
            if op in op_groups:
                v = op_groups[op][0]
                rss_per_op[op] = v.rss_kb
                pm = pm_index.get((v.sample_id, v.vma_id))
                ratio = pm.present_ratio if pm else 0.0
                ratio_per_op[op] = ratio

                if ratio >= threshold or v.rss_kb >= min_rss_kb:
                    has_physical += 1
                    present_in.append(op)
                else:
                    absent_from.append(op)
            else:
                absent_from.append(op)
                rss_per_op[op] = 0
                ratio_per_op[op] = 0.0

        persistence = has_physical / n_ops if n_ops > 0 else 0.0

        # 决策: should_keep
        if persistence >= 0.66:
            should_keep = 'YES'
            reason = f"跨 {has_physical}/{n_ops} 个操作持续驻留 ({', '.join(present_in)})"
        elif persistence == 0:
            should_keep = 'NO'
            reason = "所有操作中均无显著物理驻留"
        elif persistence < 0.34:
            should_keep = 'CONDITIONAL'
            reason = f"仅在 {', '.join(present_in)} 操作中有驻留，其他操作中可回收"
        else:
            should_keep = 'CONDITIONAL'
            reason = f"在 {has_physical}/{n_ops} 操作中有驻留，取决于后续操作是否复用"

        # 特殊判断：只在最后一个操作出现
        if present_in == [operations[-1]]:
            should_keep = 'YES'
            reason = f"最新操作 {operations[-1]} 独有，尚未知未来是否复用，暂保留"

        vma_analyses.append({
            'vma_key': key,
            'pathname': rep.pathname,
            'region_type': rep.region_type,
            'perms': rep.perms,
            'vma_size_kb': rep.vma_size_kb,
            'present_in_ops': present_in,
            'absent_from_ops': absent_from,
            'rss_per_op': rss_per_op,
            'present_ratio_per_op': ratio_per_op,
            'persistence': persistence,
            'should_keep': should_keep,
            'reason': reason,
        })

    # 构建操作转换矩阵
    for i, op_a in enumerate(operations):
        for j, op_b in enumerate(operations):
            if i >= j:
                continue
            shared = []
            only_a = []
            only_b = []
            for va in vma_analyses:
                in_a = op_a in va['present_in_ops']
                in_b = op_b in va['present_in_ops']
                if in_a and in_b:
                    shared.append(va['vma_key'])
                elif in_a:
                    only_a.append(va['vma_key'])
                elif in_b:
                    only_b.append(va['vma_key'])
            transition_matrix[(op_a, op_b)] = {
                'shared': shared,
                'only_a': only_a,
                'only_b': only_b,
            }

    # 按 persistence 降序
    vma_analyses.sort(key=lambda x: x['persistence'], reverse=True)

    return {
        'operations': operations,
        'vma_analyses': vma_analyses,
        'transition_matrix': transition_matrix,
    }


# ====== 报告输出 ======

def print_report(analysis: dict, threshold: float, min_rss_kb: int):
    operations = analysis['operations']
    vmas = analysis['vma_analyses']
    tmatrix = analysis['transition_matrix']

    n_total = len(vmas)
    n_keep = sum(1 for v in vmas if v['should_keep'] == 'YES')
    n_cond = sum(1 for v in vmas if v['should_keep'] == 'CONDITIONAL')
    n_kill = sum(1 for v in vmas if v['should_keep'] == 'NO')

    keep_rss = sum(v['rss_per_op'].get(operations[-1], 0) for v in vmas if v['should_keep'] == 'YES')
    kill_rss = sum(v['rss_per_op'].get(operations[-1], 0) for v in vmas if v['should_keep'] == 'NO')
    cond_rss = sum(v['rss_per_op'].get(operations[-1], 0) for v in vmas if v['should_keep'] == 'CONDITIONAL')

    print(f"""
================================================================================
  操作级内存持久性分析报告
================================================================================
操作序列:    {' → '.join(operations)}
  """)
    for i, op in enumerate(operations):
        print(f"  [{i+1}] {op}")

    print(f"""
阈值:        present_ratio ≥ {threshold}, RSS ≥ {min_rss_kb} KB 视为显著
分析 VMA:    {n_total} 个（已筛选有物理驻留的区域）
================================================================================

## 决策摘要

| 决策 | VMA 数 | 占比 | 当前 RSS |
|------|:-----:|:----:|:--------:|
| KEEP — 跨操作持久，不应杀掉 | {n_keep} | {n_keep/n_total*100:.1f}% | {keep_rss/1024:.1f} MB |
| CONDITIONAL — 视情况保留 | {n_cond} | {n_cond/n_total*100:.1f}% | {cond_rss/1024:.1f} MB |
| KILL — 可安全回收 | {n_kill} | {n_kill/n_total*100:.1f}% | {kill_rss/1024:.1f} MB |

---
""")

    # 操作转换矩阵
    print("## 操作转换矩阵 — 跨操作内存共享\n")
    print(f"| 转换 | 共享 VMA | op_A 独有 | op_B 独有 |")
    print(f"|------|:--------:|:---------:|:---------:|")
    for (op_a, op_b), m in sorted(tmatrix.items()):
        shared_rss = sum(
            next((v['rss_per_op'].get(op_b, 0) for v in vmas if v['vma_key'] == k), 0)
            for k in m['shared'][:100]
        )
        print(f"| {op_a} → {op_b} | {len(m['shared'])} | {len(m['only_a'])} | {len(m['only_b'])} |")

    # KEEP 区域详情
    print(f"\n---\n\n## KEEP — 跨操作持久区域（不应杀掉）\n")
    print(f"| 路径 | 类型 | 大小 | 操作覆盖 | RSS 趋势 |")
    print(f"|------|------|------|----------|---------|")
    keep_shown = 0
    for v in vmas:
        if v['should_keep'] != 'YES':
            continue
        keep_shown += 1
        if keep_shown <= 40:
            rss_trend = ' → '.join(f"{v['rss_per_op'].get(op, 0)} KB" for op in operations)
            op_tags = ''.join('✓' if op in v['present_in_ops'] else '✗' for op in operations)
            print(f"| `{v['pathname'][:70]}` | {v['region_type']} | "
                  f"{v['vma_size_kb']} KB | {op_tags} | {rss_trend} |")

    if keep_shown > 40:
        print(f"\n... 还有 {n_keep - 40} 个 KEEP 区域\n")
    elif keep_shown == 0:
        print("| (无) | | | | |")

    # 按区域类型汇总
    print(f"\n---\n\n## 按区域类型的 Keep/Kill 建议\n")
    by_type = defaultdict(lambda: {'keep': 0, 'kill': 0, 'cond': 0, 'keep_rss': 0, 'kill_rss': 0})
    for v in vmas:
        t = v['region_type']
        cat = v['should_keep']
        by_type[t][{'YES': 'keep', 'NO': 'kill', 'CONDITIONAL': 'cond'}[cat]] += 1
        rss = v['rss_per_op'].get(operations[-1], 0)
        by_type[t][{'YES': 'keep_rss', 'NO': 'kill_rss', 'CONDITIONAL': 'cond'}[cat]] += rss

    print(f"| 区域类型 | KEEP | KILL | COND | KEEP RSS | KILL RSS | 建议 |")
    print(f"|----------|:----:|:----:|:----:|:--------:|:--------:|------|")
    for t, stats in sorted(by_type.items(), key=lambda x: x[1]['keep_rss'], reverse=True):
        suggestion = ""
        if stats['keep'] > stats['kill'] * 2:
            suggestion = "倾向保留"
        elif stats['kill'] > stats['keep'] * 2:
            suggestion = "倾向回收"
        else:
            suggestion = "需逐项判断"
        print(f"| {t} | {stats['keep']} | {stats['kill']} | {stats['cond']} | "
              f"{stats['keep_rss']/1024:.1f} MB | {stats['kill_rss']/1024:.1f} MB | {suggestion} |")

    # KILL 区域 Top 20（按 RSS）
    print(f"\n---\n\n## Top 20 可回收区域（按 RSS 降序）\n")
    kill_vmas = sorted(
        [v for v in vmas if v['should_keep'] == 'NO'],
        key=lambda x: x['rss_per_op'].get(operations[-1], 0), reverse=True
    )
    print(f"| 路径 | 类型 | 大小 | 最新 RSS | 原因 |")
    print(f"|------|------|------|:--------:|------|")
    for v in kill_vmas[:20]:
        latest_rss = v['rss_per_op'].get(operations[-1], 0)
        print(f"| `{v['pathname'][:70]}` | {v['region_type']} | "
              f"{v['vma_size_kb']} KB | {latest_rss} KB | {v['reason']} |")

    print(f"\n---\n*报告由 analyze_operations.py 生成 | threshold={threshold} | min_rss={min_rss_kb} KB*")


# ====== CSV 输出 ======

def write_label_csv(analysis: dict, csv_dir: str, snapshots: List[SnapshotMeta]):
    """将分析结果写入 future_need_label.csv。"""
    path = os.path.join(csv_dir, 'future_need_label.csv')
    operations = analysis['operations']
    vmas = analysis['vma_analyses']

    sample_to_meta = {s.sample_id: s for s in snapshots}

    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'label_id', 'sample_id', 'operation_id', 'next_operation_id',
            'app_id', 'app_name', 'process_name', 'pid',
            'vma_id', 'region_type',
            'revisit_in_1s', 'revisit_in_3s', 'revisit_in_5s',
            'should_keep', 'reason', 'note'
        ])

        label_id = 1
        for v in vmas:
            for op in operations:
                # 为每个 VMA x 操作组合写标签
                op_samples_in = [s for s in snapshots if s.operation_id == op]
                if not op_samples_in:
                    continue
                sample = op_samples_in[0]

                # 确定下一个操作
                op_idx = operations.index(op)
                next_op = operations[op_idx + 1] if op_idx + 1 < len(operations) else ''

                rss = v['rss_per_op'].get(op, 0)
                writer.writerow([
                    f"label_{label_id:06d}",
                    sample.sample_id,
                    op,
                    next_op,
                    '',  # app_id
                    '',  # app_name
                    sample.process_name,
                    sample.pid,
                    '',  # vma_id (通配)
                    v['region_type'],
                    '', '', '',  # revisit timings (unknown)
                    v['should_keep'],
                    v['reason'],
                    f"vma_key={v['vma_key']} rss={rss}KB persistence={v['persistence']:.2f}",
                ])
                label_id += 1

    print(f"[输出] {label_id - 1} 条标签写入 {path}", file=sys.stderr)


# ====== 入口 ======

def main():
    parser = argparse.ArgumentParser(
        description='操作级内存持久性分析 — 哪些地址空间不应该被杀掉',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -i memcap_out/
  %(prog)s -i memcap_out/ --threshold 0.1 --min-rss 50
  %(prog)s -i memcap_out/ --export-labels    # 输出 future_need_label.csv
        """)
    parser.add_argument('-i', '--input', default='memcap_out', help='CSV 目录')
    parser.add_argument('--threshold', type=float, default=0.1,
                        help='present_ratio 阈值 (默认: 0.1)')
    parser.add_argument('--min-rss', type=int, default=50,
                        help='最小 RSS (KB) 过滤 (默认: 50)')
    parser.add_argument('--sample', nargs='*', default=None,
                        help='只分析指定 sample_id (可多个)')
    parser.add_argument('--session-gap-min', type=int, default=30,
                        help='会话间隔阈值（分钟），超过此间隔视为不同会话 (默认: 30)')
    parser.add_argument('--export-labels', action='store_true',
                        help='输出 future_need_label.csv')
    args = parser.parse_args()

    csv_dir = args.input
    if not os.path.isdir(csv_dir):
        print(f"[错误] 目录不存在: {csv_dir}", file=sys.stderr)
        sys.exit(1)

    print("[加载] 加载数据...", file=sys.stderr)
    snapshots = parse_snapshot_index(csv_dir)
    vma_rows = parse_vma_csv(csv_dir)
    pm_rows = parse_pagemap_csv(csv_dir)

    # 构建 pagemap 索引
    pm_index = {(p.sample_id, p.vma_id): p for p in pm_rows}

    # 按 sample 筛选
    if args.sample:
        snapshots = [s for s in snapshots if s.sample_id in args.sample]

    # 自动检测会话：时间间隔 > session_gap_min 视为不同会话
    sorted_snaps = sorted(snapshots, key=lambda s: s.timestamp_ms)
    sessions = []
    current_session = [sorted_snaps[0]] if sorted_snaps else []
    for i in range(1, len(sorted_snaps)):
        gap_ms = sorted_snaps[i].timestamp_ms - sorted_snaps[i-1].timestamp_ms
        gap_min = gap_ms / 60000.0
        if gap_min > args.session_gap_min:
            sessions.append(current_session)
            current_session = [sorted_snaps[i]]
        else:
            current_session.append(sorted_snaps[i])
    if current_session:
        sessions.append(current_session)

    if len(sessions) > 1:
        print(f"[会话] 检测到 {len(sessions)} 个独立会话（间隔 > {args.session_gap_min} 分钟）", file=sys.stderr)
        for i, sess in enumerate(sessions):
            ops = ', '.join(s.operation_id for s in sess)
            print(f"  会话 {i+1}: {len(sess)} 个快照 — {ops}", file=sys.stderr)
        # 默认使用快照最多的会话
        target_snaps = max(sessions, key=len)
        print(f"[选择] 使用会话 (快照数最多): {len(target_snaps)} 个快照", file=sys.stderr)
    else:
        target_snaps = snapshots

    # 过滤：只留斗鱼相关
    douyu_snaps = [s for s in target_snaps if '斗鱼' in s.process_name or 'douyu' in s.process_name.lower()]
    if douyu_snaps:
        target_snaps = douyu_snaps

    if len(target_snaps) < 2:
        print(f"[错误] 快照数不足: {len(target_snaps)} (需要 ≥ 2)", file=sys.stderr)
        sys.exit(1)

    print(f"[分析] {len(target_snaps)} 个快照, {len(set(s.operation_id for s in target_snaps))} 个操作",
          file=sys.stderr)
    for s in target_snaps:
        print(f"  {s.operation_id:30s}  PID={s.pid:<6d}  {s.foreground_state}  {s.sample_id}",
              file=sys.stderr)

    analysis = analyze_operations(target_snaps, vma_rows, pm_index,
                                   args.threshold, args.min_rss)

    print_report(analysis, args.threshold, args.min_rss)

    if args.export_labels:
        write_label_csv(analysis, csv_dir, target_snaps)


if __name__ == '__main__':
    main()
