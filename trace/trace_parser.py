import struct, os, json

EVENT_STRUCT_FMT = "<QQQQQQIIIIII16s"
EVENT_STRUCT_SIZE = struct.calcsize(EVENT_STRUCT_FMT)

def parse_and_align_features(bin_path, csv_path, app_ops_path):
    if not os.path.exists(bin_path): return
    app_ops = []
    if os.path.exists(app_ops_path):
        with open(app_ops_path, 'r') as f: app_ops = json.load(f)
            
    macro_app_mapping = {op['app_op']: {"pages": []} for op in app_ops}

    with open(bin_path, "rb") as f_in, open(csv_path, "w", encoding='utf_8_sig') as f_out:
        headers = "timestamp,op_id,app_op,pid,tid,comm,event_type,op_type,ino,offset,major,minor,op_duration_us\n"
        f_out.write(headers)

        while True:
            data = f_in.read(EVENT_STRUCT_SIZE)
            if not data or len(data) < EVENT_STRUCT_SIZE: break
            ts, op_id, ino, offset, fsize, dur_ns, pid, tid, ev_type, op_t, maj, min, comm_bytes = struct.unpack(EVENT_STRUCT_FMT, data)
            
            comm = comm_bytes.split(b'\x00', 1)[0].decode('utf-8', 'ignore').strip()
            ev_str = {0: "ACCESS", 1: "INSERT", 2: "EVICT", 3: "OP_DONE"}.get(ev_type, "UNK")
            
           
            if op_t == 1:
                op_str = "VFS_READ"
            elif op_t == 2:
                op_str = "VFS_WRITE"
            else:
                # 针对 NONE 的具象化逻辑
                if ev_type == 0: op_str = "MEM_HIT"       # 内存命中访问
                elif ev_type == 1: op_str = "MMAP_LOAD"   # 内存映射加载（对应冷启动加载）
                elif ev_type == 2: op_str = "RECLAIM"     # 内存回收
                else: op_str = "OTHER"
            

            dur_us = dur_ns / 1000.0
            current_app_op = "NONE"
            for op in app_ops:
                if op['start_ts'] <= ts <= op['end_ts']:
                    current_app_op = op['app_op']
                    break
            
            f_out.write(f"{ts},{op_id},{current_app_op},{pid},{tid},{comm},{ev_str},{op_str},{ino},{offset},{maj},{min},{dur_us:.2f}\n")

    print(f"[+] 解析成功！")

if __name__ == "__main__":
    parse_and_align_features("raw_trace.bin", "aligned_trace.csv", "app_operations.json")
