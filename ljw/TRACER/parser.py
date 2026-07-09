#!/usr/bin/env python3
import struct
import sys
import os
import json

EVENT_STRUCT_FMT = "<QQQQQQIIIIII16s"
EVENT_STRUCT_SIZE = struct.calcsize(EVENT_STRUCT_FMT)

MISSING_DELTA_VAL = 18446744073709551615
DEFAULT_SEQ_DISTANCE = 4294967295

def parse_and_align_features(bin_path, csv_path):
    if not os.path.exists(bin_path):
        print(f"错误: 找不到二进制日志文件 {bin_path}")
        return

    page_history, inode_history = {}, {}
    page_ema, inode_ema = {}, {}
    op_mapping = {}

    print(f"开始解析 {bin_path} 并计算特征对齐矩阵...")

    with open(bin_path, "rb") as f_in, open(csv_path, "w") as f_out:
        headers = "timestamp,op_id,pid,tid,comm,event_type,op_type,ino,offset,major,minor,page_time_delta,page_time_delta2,inode_time_delta,inode_time_delta2,seq_distance,file_size,frequency,inode_hotness_ema,op_duration_us"
        f_out.write(headers + "\n")

        count = 0
        while True:
            data = f_in.read(EVENT_STRUCT_SIZE)
            if not data or len(data) < EVENT_STRUCT_SIZE: break

            ts, op_id, ino, offset, file_size, op_duration_ns, pid, tid, ev_type, op_type, major, minor, comm_bytes = struct.unpack(EVENT_STRUCT_FMT, data)
            
            # 【强力清理 comm 乱码】：去掉所有的奇怪换行符、逗号，确保纯净
            raw_comm = comm_bytes.split(b'\x00', 1)[0].decode('utf-8', 'ignore')
            clean_comm = "".join([c if c.isalnum() or c in "-_" else "_" for c in raw_comm]).strip()
            if not clean_comm: clean_comm = "UNKNOWN_PROC"

            ev_str = {0: "ACCESS", 1: "INSERT", 2: "EVICT", 3: "OP_DONE"}.get(ev_type, "UNKNOWN")
            op_str = {1: "READ", 2: "WRITE"}.get(op_type, "NONE") if ev_type == 3 or op_type > 0 else "NONE"

            # ---------------- 新增功能：处理映射表映射关系 ----------------
            if op_id != 0:
                if op_id not in op_mapping:
                    op_mapping[op_id] = {
                        "start_ts": 0, 
                        "end_ts": 0,
                        "duration_ns": 0, 
                        "op_type": "UNKNOWN",
                        "pages": []
                    }
                
                # 若为当前操作的结束标记：更新时间区间
                if ev_type == 3:
                    op_mapping[op_id]["duration_ns"] = op_duration_ns
                    op_mapping[op_id]["op_type"] = op_str
                    op_mapping[op_id]["end_ts"] = ts
                    op_mapping[op_id]["start_ts"] = ts - op_duration_ns
                else:
                    # 记录具体的页面行为（带上了当前的时间戳用于观察顺序）
                    op_mapping[op_id]["pages"].append({"ino": ino, "offset": offset, "event": ev_str, "ts": ts})

            p_key = (ino, offset)
            p_time_delta = MISSING_DELTA_VAL
            p_time_delta2 = MISSING_DELTA_VAL
            if p_key in page_history:
                last_access, prev_access = page_history[p_key]
                p_time_delta = ts - last_access if ts >= last_access else 0
                if prev_access != 0: p_time_delta2 = last_access - prev_access if last_access >= prev_access else 0
                page_history[p_key] = [ts, last_access]
            else: page_history[p_key] = [ts, 0]

            i_time_delta = MISSING_DELTA_VAL
            i_time_delta2 = MISSING_DELTA_VAL
            seq_distance = DEFAULT_SEQ_DISTANCE
            if ino in inode_history:
                last_access, prev_access, last_offset = inode_history[ino]
                i_time_delta = ts - last_access if ts >= last_access else 0
                if prev_access != 0: i_time_delta2 = last_access - prev_access if last_access >= prev_access else 0
                seq_distance = abs(int(offset) - int(last_offset))
                inode_history[ino] = [ts, last_access, offset]
            else: inode_history[ino] = [ts, 0, offset]

            p_freq = 1000
            if p_key in page_ema:
                old_score, last_ema_ts = page_ema[p_key]
                delta_sec = max(0, (ts - last_ema_ts) / 1e9)
                p_freq = int(1000 + (0.0 if delta_sec > 100.0 else old_score * (0.5 ** delta_sec)))
                page_ema[p_key] = [p_freq, ts]
            else: page_ema[p_key] = [1000, ts]

            i_ema = 1000
            if ino in inode_ema:
                old_score, last_ema_ts = inode_ema[ino]
                delta_sec = max(0, (ts - last_ema_ts) / 1e9)
                i_ema = int(1000 + (0.0 if delta_sec > 100.0 else old_score * (0.5 ** delta_sec)))
                inode_ema[ino] = [i_ema, ts]
            else: inode_ema[ino] = [1000, ts]

            op_duration_us = f"{op_duration_ns / 1000.0:.2f}" if ev_type == 3 else "0.0"

            csv_row = (
                f"{ts},{op_id},{pid},{tid},{clean_comm},{ev_str},{op_str},{ino},{offset},{major},{minor},"
                f"{p_time_delta},{p_time_delta2},{i_time_delta},{i_time_delta2},{seq_distance},"
                f"{file_size},{p_freq},{i_ema},{op_duration_us}\n"
            )
            f_out.write(csv_row)
            count += 1

    print(f"解析成功！共处理 {count} 条物理事件，特征文件已保存至 {csv_path}")
    
    with open("operation_to_pages.json", 'w') as f_map:
        json.dump(op_mapping, f_map, indent=4)
    print("已生成 操作与页面映射表： operation_to_pages.json")

if __name__ == "__main__":
    parse_and_align_features("raw_trace.bin", "aligned_trace_features.csv")
