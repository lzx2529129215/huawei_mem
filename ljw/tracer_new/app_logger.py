#!/usr/bin/env python3
import time, json, os
vocab_file = "op_vocab.json"
with open(vocab_file, 'r', encoding='utf-8') as f: vocab = json.load(f)
app_ops = []
app_list = list(vocab.keys())
while True:
    for i, name in enumerate(app_list): print(f"[{i}] {name}")
    choice = input("应用序号 (q退出): ")
    if choice == 'q': break
    app = app_list[int(choice)]
    ops = [k for k in vocab[app].keys() if k not in ("<PAD>", "<UNK>")]
    for i, o in enumerate(ops): print(f"[{i}] {o}")
    o_choice = input("操作序号: ")
    start = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    input(">>> 请在 A 终端启动应用后，回到此处按回车结束 <<<")
    end = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    app_ops.append({"app_op": f"{app}_{ops[int(o_choice)]}", "start_ts": start, "end_ts": end})
with open("app_operations.json", "w") as f: json.dump(app_ops, f, indent=4)
