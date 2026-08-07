# Linux 6.17 memory-scheduling experiments

This repository implements a measurement-first reproduction framework aligned with:

- Acclaim: page refault, direct reclaim, 0/3/8/15 background-app scenarios, five-minute foreground use.
- AppFlow: GB-scale cold launch, 5/15/15+2 background workloads, I/O throughput, direct reclaim and kill events.
- Fleet: cached-app capacity, 512/2048-byte managed objects, 180 MB per synthetic app, hot launch, GC/object proxies, FPS and jank.

The target is a dedicated Linux 6.17 test machine. The repository does not pretend that Android-only metrics exist for native Linux QQ/WPS: LMKD, ART Java heap and ART object re-access are reported as `N/A` unless an Android/JVM-specific probe supplies them.

## Quick start on the Linux 6.17 test host

```bash
cd /path/to/linux6.17_test
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

bash scripts/install_qq_wps_ubuntu.sh
bash scripts/preflight.sh
bash scripts/run_qq_wps_round.sh
```

`configs/qq_wps.json` controls application commands, process names, window patterns, duration, interval and repetitions. The checked-in configuration performs the requested single cold-start round for QQ and WPS; use `COLD_REPETITIONS=N` to expand it.

The installer accepts current official direct-package links when the vendor pages are rendered by JavaScript:

```bash
QQ_DEB_URL='https://official.example/linuxqq_amd64.deb' \
WPS_DEB_URL='https://official.example/wps_x86_64.deb' \
bash scripts/install_qq_wps_ubuntu.sh
```

Do not enable `DROP_CACHES=1` on a shared machine. On an isolated experiment host, a strict cold-cache run is:

```bash
DROP_CACHES=1 DURATION_SECONDS=60 bash scripts/run_qq_wps_round.sh
```

## Paper-aligned workloads

Scenario runners reject an effective memory budget above their paper-aligned ceiling (Acclaim/Fleet: 4 GiB, AppFlow: 8 GiB). The guard detects boot limits and the smallest enclosing cgroup-v2 `memory.max`. `ALLOW_UNCONSTRAINED_MEMORY=1` is only for a clearly labelled smoke test.

```bash
# Acclaim: run each background count, ten repetitions each.
bash scripts/scenarios/run_acclaim.sh 0
bash scripts/scenarios/run_acclaim.sh 3
bash scripts/scenarios/run_acclaim.sh 8
bash scripts/scenarios/run_acclaim.sh 15

# AppFlow: fully written 1.2 GiB target read under three pressure levels.
bash scripts/scenarios/run_appflow.sh low
bash scripts/scenarios/run_appflow.sh medium
bash scripts/scenarios/run_appflow.sh high

# Fleet: managed-object proxy workloads.
bash scripts/scenarios/run_fleet.sh 512 18
bash scripts/scenarios/run_fleet.sh 2048 18
```

For an app-specific cgroup, launch it as a transient user service and pass the printed cgroup path to the collector:

```bash
CGROUP_PATH="$(bash scripts/create_user_cgroup_scope.sh memexp-qq qq)"
python3 -m memsched_exp.cli collect \
  --name qq --duration 60 --cgroup "$CGROUP_PATH" --output results/qq-cgroup
```

## Output

Every run contains immutable raw inputs (`before.json`, `after.json`, `samples.jsonl`), metadata, and `summary.json`. When eBPF is enabled it also contains `reclaim-events.jsonl` and `reclaim-events-summary.json`. Launch and frame analyses are stored separately so their measurement source is auditable.

Metadata includes the kernel-config hash, swap/zram, VM sysctls, THP, CPU governor, session and result filesystem. QQ/WPS additionally record executable SHA-256 and Debian package version. Invalid cgroup endpoints, unpaired/lost eBPF events and launch timeouts are reported as invalid rather than converted to zero.

Aggregate completed runs without discarding raw counters:

```bash
python3 -m memsched_exp.report --root results --output results/summary.csv
```

See [the detailed experiment design](docs/EXPERIMENT_DESIGN.md) and [the metric dictionary](docs/METRICS.md).

For Windows-hosted development and Linux VM operation, follow the [VS Code + Linux 6.17 VM operation guide](docs/VSCODE_VM_OPERATION_GUIDE.md).
