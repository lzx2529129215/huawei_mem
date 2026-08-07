#!/usr/bin/env python3
import os, time, subprocess, sys

def watch_and_move(keyword, cgroup_path):
    cgroup_procs = os.path.join(cgroup_path, "cgroup.procs")
    already_moved = set()
    input(f"--- 守卫就绪 --- \n请确保 B 追踪已开。在这里【按回车】后立刻去 A 启动应用！")
    print(f"[*] 正在捕捉关键词 '{keyword}'...")
    start_time = time.time()
    while time.time() - start_time < 15: # 捕捉持续 15 秒
        try:
            cmd = f"ps -ef | grep {keyword} | grep -v grep | awk '{{print $2}}'"
            pids = subprocess.check_output(cmd, shell=True).decode().split()
            for pid in pids:
                if pid not in already_moved:
                    with open(cgroup_procs, 'w') as f: f.write(pid)
                    already_moved.add(pid)
                    print(f"[+] 捕捉 PID: {pid}")
        except: pass
        time.sleep(0.05)
    print(f"[*] 捕捉完成，共抓取 {len(already_moved)} 个进程。")

if __name__ == "__main__":
    watch_and_move(sys.argv[1], sys.argv[2])
