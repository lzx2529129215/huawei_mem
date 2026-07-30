# Linux L0.2 Classic-LRU lruvec Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an observe-only Linux 6.17 classic-LRU `lruvec` observer that emits request and per-scan snapshots through tracepoint/debugfs, parses and stores them in user space, and performs read-only comparison against Shadow physical LRU aggregates.

**Architecture:** The kernel side extends the existing L0.1 kswapd observer with an explicit request/priority/scan context, a classic-LRU resolver, MGLRU guards, bounded debugfs snapshots, and optional bounded folio samples. Kernel changes remain in an ignored Linux 6.17 work tree and are delivered as audited patch files. The user-space side introduces a C snapshot model, parser, ordered store, bootstrap aggregate, read-only Shadow alignment, CLI, and tests.

**Tech Stack:** Linux 6.17 MM internals, C11/C17, KUnit, tracepoints/tracefs, debugfs/seq_file, pthread-safe user-space C, CMake/CTest, Python 3 capture tooling, shell build scripts, Git worktrees.

## Global Constraints

- Work only in `/home/lzx/Desktop/huawei/myself-kswapd-l02`.
- Branch must remain `feat/linux-l02-lruvec-observer`.
- Starting design commit is `e6f9e15f4d32d2200d28fe6c063d3482577600e9`.
- Replace the original spec with the approved v2 spec before production work.
- Do not merge `main`; do not push.
- Do not modify or delete the L0.1, Shadow, integration, or main worktrees.
- Linux observer behavior is strictly observe-only.
- Do not change native LRU lists, folio flags, reclaim priority, scan balance, writeback, swap, or native return values.
- Do not implement PAGE_ADD/ACTIVATE/DEACTIVATE/MOVE/ISOLATE/PUTBACK/RECLAIMED.
- Do not implement DEMOTE/RECLAIM/PROTECT/PREWASH execution.
- Do not support MGLRU; reject classic snapshots when MGLRU is enabled.
- The formal observation key is `(mode, memcg_id, nid)`.
- Linux `CONFIG_MEMCG=y` supports only MEMCG mode; GLOBAL mode is not a root-memcg alias.
- Linux `CONFIG_MEMCG=n` supports only GLOBAL mode.
- `NR_ISOLATED_ANON/FILE` are NODE-scope fields.
- In MEMCG mode, isolated counts are diagnostic only and do not participate in per-memcg MATCH.
- Request events and lruvec snapshot events are separate.
- Every scan snapshot is identified by `(request_id, priority_seq, scan_seq)`.
- `snapshot_seq` is a global monotonic transport sequence.
- Trace producer code must not claim an exact trace-buffer drop count.
- debugfs `snapshot` performs one collection per `open()`, not one collection per `read()`.
- debugfs `samples` returns cached data and never triggers a new LRU walk.
- Normal reclaim hot paths never enumerate all memcgs, all nodes, or folios.
- Folio sampling is debug-only, bounded, and disabled by default.
- Shadow alignment reads physical aggregates only and never mutates Shadow state.
- Preserve the project comment convention for new/modified C code:
  - `// #lzx`
  - `// #old: ...`
  - `// #lzx---------------------------`
- Use test-first RED → GREEN → REFACTOR for every behavior change.
- After every kernel task, refresh and review the tracked L0.2 patch.
- Every task ends with focused tests, `git diff --check`, and a commit.
- Runtime smoke is reported as `NOT RUN / ENVIRONMENT BLOCKED` when a bootable test kernel is unavailable.

---

## Planned File Structure

### Tracked repository files

- Modify: `docs/superpowers/specs/2026-07-28-linux-l02-lruvec-observer-design.md`
- Create: `docs/superpowers/plans/2026-07-28-linux-l02-lruvec-observer-plan.md`
- Import: `patches/0002-linux617-myself-kswapd-l01.patch`
- Create: `patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch`
- Create: `tools/myself_kswapd/bootstrap_linux617_l02_tree.sh`
- Create: `tools/myself_kswapd/refresh_linux617_l02_patch.sh`
- Import/modify: `tools/myself_kswapd/parse_kswapd_trace.py`
- Import/modify: `tools/myself_kswapd/capture_kswapd_trace.sh`
- Create: `tools/myself_kswapd/parse_lruvec_trace.py`
- Create: `tools/myself_kswapd/tests/test_parse_lruvec_trace.py`
- Modify: `用户态模拟器/v1/CMakeLists.txt`
- Create: `用户态模拟器/v1/include/myself_kswapd/kernel_lruvec_snapshot.h`
- Create: `用户态模拟器/v1/include/myself_kswapd/kernel_snapshot_store.h`
- Create: `用户态模拟器/v1/include/myself_kswapd/shadow_alignment.h`
- Create: `用户态模拟器/v1/src/l02/lruvec_trace_parser.c`
- Create: `用户态模拟器/v1/src/l02/kernel_snapshot_store.c`
- Create: `用户态模拟器/v1/src/l02/bootstrap_aggregate.c`
- Create: `用户态模拟器/v1/src/l02/shadow_alignment.c`
- Create: `用户态模拟器/v1/tools/lruvec_observer_cli.c`
- Create: `用户态模拟器/v1/tests/unit/test_lruvec_trace_parser.c`
- Create: `用户态模拟器/v1/tests/unit/test_kernel_snapshot_store.c`
- Create: `用户态模拟器/v1/tests/unit/test_shadow_alignment.c`
- Create: `用户态模拟器/v1/tests/integration/test_l02_observer_pipeline.c`
- Modify only if needed: `用户态模拟器/v1/include/myself_kswapd/shadow_lru.h`
- Modify only if needed: `用户态模拟器/v1/src/core/shadow_lru.c`

### Ignored Linux 6.17 work-tree files represented by `0003` patch

- Modify: `Linux6.17/mm/vmscan.c`
- Modify: `Linux6.17/mm/myself_kswapd/Kconfig`
- Modify: `Linux6.17/mm/myself_kswapd/Makefile`
- Modify: `Linux6.17/mm/myself_kswapd/include/kswapd_observer.h`
- Create: `Linux6.17/mm/myself_kswapd/include/lruvec_observer.h`
- Modify: `Linux6.17/mm/myself_kswapd/adapter/kswapd_observer.c`
- Create: `Linux6.17/mm/myself_kswapd/adapter/lruvec_observer.c`
- Create: `Linux6.17/mm/myself_kswapd/debugfs/lruvec_debugfs.c`
- Create: `Linux6.17/mm/myself_kswapd/trace/lruvec_trace.h`
- Modify: `Linux6.17/mm/myself_kswapd/trace/trace.c`
- Create: `Linux6.17/mm/myself_kswapd/tests/lruvec_observer_test.c`
- Modify: `Linux6.17/mm/myself_kswapd/tests/Makefile`

If the real L0.1 paths differ, Codex must preserve the same responsibilities while using the actual existing paths. It must record every path adjustment in the implementation report before editing.

---

## Core Interfaces Frozen by This Plan

### Kernel key and snapshot

```c
enum myks_lru_mode {
    MYKS_LRU_MODE_MEMCG = 0,
    MYKS_LRU_MODE_GLOBAL,
};

enum myks_field_scope {
    MYKS_SCOPE_INVALID = 0,
    MYKS_SCOPE_MEMCG_NODE,
    MYKS_SCOPE_NODE,
};

enum myks_reclaim_source {
    MYKS_RECLAIM_KSWAPD = 0,
    MYKS_RECLAIM_DIRECT,
    MYKS_RECLAIM_MEMCG,
    MYKS_RECLAIM_UNKNOWN,
};

enum myks_snapshot_stage {
    MYKS_STAGE_SCAN_BEFORE = 0,
    MYKS_STAGE_SCAN_AFTER,
    MYKS_STAGE_HEARTBEAT,
    MYKS_STAGE_DEBUGFS,
};

enum myks_snapshot_consistency {
    MYKS_SNAPSHOT_APPROXIMATE = 0,
    MYKS_SNAPSHOT_LOCKED_SAMPLE,
};

struct myks_lruvec_key {
    enum myks_lru_mode mode;
    u64 memcg_id;
    int nid;
};

struct myks_lruvec_snapshot {
    u64 snapshot_seq;
    u64 timestamp_ns;
    u64 request_id;
    u64 priority_seq;
    u64 scan_seq;

    struct myks_lruvec_key key;
    u32 memcg_css_id;

    enum myks_reclaim_source reclaim_source;
    enum myks_snapshot_stage stage;
    enum myks_snapshot_consistency consistency;
    int priority;

    unsigned long inactive_anon;
    unsigned long active_anon;
    unsigned long inactive_file;
    unsigned long active_file;
    unsigned long isolated_anon;
    unsigned long isolated_file;

    unsigned long scanned_total;
    unsigned long reclaimed_total;

    u64 field_valid_mask;
    u64 validation_flags;
};
```

### Request context

```c
struct myks_reclaim_observer_ctx {
    u64 request_id;
    u64 priority_seq;
    u64 next_scan_seq;
    enum myks_reclaim_source source;
    bool active;
};
```

### Kernel collection API

```c
int myks_lruvec_resolve(
    enum myks_lru_mode mode,
    struct mem_cgroup *memcg,
    pg_data_t *pgdat,
    struct myks_lruvec_identity *identity,
    struct lruvec **lruvec);

int myks_lruvec_collect(
    const struct myks_reclaim_observer_ctx *ctx,
    u64 scan_seq,
    struct lruvec *lruvec,
    pg_data_t *pgdat,
    enum myks_snapshot_stage stage,
    int priority,
    unsigned long scanned_total,
    unsigned long reclaimed_total,
    struct myks_lruvec_snapshot *out);
```

### User-space canonical model

User-space mirrors the kernel scalar contract with fixed-width integer types:

```c
struct kernel_lruvec_key {
    enum kernel_lru_mode mode;
    uint64_t memcg_id;
    int32_t nid;
};

struct kernel_lruvec_snapshot {
    uint64_t snapshot_seq;
    uint64_t timestamp_ns;
    uint64_t request_id;
    uint64_t priority_seq;
    uint64_t scan_seq;
    struct kernel_lruvec_key key;
    uint32_t memcg_css_id;
    enum kernel_reclaim_source reclaim_source;
    enum kernel_snapshot_stage stage;
    enum kernel_snapshot_consistency consistency;
    int32_t priority;
    uint64_t inactive_anon;
    uint64_t active_anon;
    uint64_t inactive_file;
    uint64_t active_file;
    uint64_t isolated_anon;
    uint64_t isolated_file;
    uint64_t scanned_total;
    uint64_t reclaimed_total;
    uint64_t field_valid_mask;
    uint64_t validation_flags;
};
```

---

### Task 1: Freeze the Approved Spec and Plan

**Files:**
- Modify: `docs/superpowers/specs/2026-07-28-linux-l02-lruvec-observer-design.md`
- Create: `docs/superpowers/plans/2026-07-28-linux-l02-lruvec-observer-plan.md`

**Interfaces:**
- Consumes: approved v2 design document and this plan.
- Produces: committed design/plan baseline for every later task.

- [ ] **Step 1: Verify branch and clean worktree**

Run:

```bash
cd /home/lzx/Desktop/huawei/myself-kswapd-l02
git branch --show-current
git rev-parse HEAD
git status --short --branch
```

Expected:

```text
feat/linux-l02-lruvec-observer
e6f9e15f4d32d2200d28fe6c063d3482577600e9
clean
```

Stop if branch, HEAD ancestry, or cleanliness differs.

- [ ] **Step 2: Replace the original spec with the approved v2 document**

Copy the approved document to:

```text
docs/superpowers/specs/2026-07-28-linux-l02-lruvec-observer-design.md
```

Copy this plan to:

```text
docs/superpowers/plans/2026-07-28-linux-l02-lruvec-observer-plan.md
```

- [ ] **Step 3: Verify the design no longer contains interface-level open questions**

Run:

```bash
grep -nE 'OPEN QUESTION|TBD|TODO|FIXME' \
  docs/superpowers/specs/2026-07-28-linux-l02-lruvec-observer-design.md \
  docs/superpowers/plans/2026-07-28-linux-l02-lruvec-observer-plan.md
```

Expected: no unresolved placeholder. References explaining that old open questions are closed are allowed only when followed by final decisions.

- [ ] **Step 4: Review diff**

Run:

```bash
git diff --check
git diff --stat
git diff --name-only
```

Expected: only the two documentation files.

- [ ] **Step 5: Commit**

```bash
git add \
  docs/superpowers/specs/2026-07-28-linux-l02-lruvec-observer-design.md \
  docs/superpowers/plans/2026-07-28-linux-l02-lruvec-observer-plan.md

git commit -m "docs: freeze Linux L0.2 observer implementation plan"
```

---

### Task 2: Import L0.1 Observe-Only Prerequisites and Build Harness

**Files:**
- Import: `patches/0002-linux617-myself-kswapd-l01.patch`
- Create: `tools/myself_kswapd/bootstrap_linux617_l02_tree.sh`
- Create: `tools/myself_kswapd/refresh_linux617_l02_patch.sh`
- Import: `tools/myself_kswapd/README.md`
- Import: `tools/myself_kswapd/parse_kswapd_trace.py`
- Import: `tools/myself_kswapd/capture_kswapd_trace.sh`
- Import: `tools/myself_kswapd/tests/`

**Interfaces:**
- Consumes: L0.1 worktree at `/home/lzx/Desktop/huawei/myself-kswapd-l01`.
- Produces: reproducible local Linux tree bootstrap and L0.2 patch refresh workflow.

- [ ] **Step 1: Write a failing shell self-test for the bootstrap script**

Create `tools/myself_kswapd/tests/test_bootstrap_l02_tree.sh` that:

1. creates a temporary fake L0.1 source tree;
2. invokes the bootstrap script with explicit `--source` and `--dest`;
3. asserts destination files are copied;
4. asserts a second invocation refuses to overwrite a non-empty unknown destination;
5. asserts source and destination paths cannot be identical.

Run:

```bash
bash tools/myself_kswapd/tests/test_bootstrap_l02_tree.sh
```

Expected: FAIL because the script does not exist.

- [ ] **Step 2: Implement the bootstrap script**

The script must accept:

```text
--source <L0.1 Linux6.17 tree>
--dest <L0.2 Linux6.17 tree>
```

Behavior:

- source must exist;
- destination absent or empty;
- copy using `cp -a --reflink=auto`;
- never use `--delete`;
- create marker `.myks_l02_base` containing source path and timestamp;
- never modify source.

- [ ] **Step 3: Write a failing test for patch refresh**

Create `tools/myself_kswapd/tests/test_refresh_l02_patch.sh`.

The test constructs fake base/current trees with:

```text
mm/vmscan.c
mm/myself_kswapd/Kconfig
mm/myself_kswapd/Makefile
mm/myself_kswapd/include/
mm/myself_kswapd/adapter/
mm/myself_kswapd/debugfs/
mm/myself_kswapd/trace/
mm/myself_kswapd/tests/
```

It verifies the generated patch contains only those allowlisted paths and refuses path traversal.

- [ ] **Step 4: Implement the patch refresh script**

Arguments:

```text
--base <L0.1 Linux tree>
--current <L0.2 Linux tree>
--output patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch
```

Use an explicit allowlist and `git diff --no-index --binary` per path. Normalize prefixes to:

```text
a/Linux6.17/...
b/Linux6.17/...
```

Return success when no L0.2 diff exists and create an empty patch only when `--allow-empty` is given.

- [ ] **Step 5: Import L0.1 tracked prerequisites**

Copy exact files from the L0.1 worktree. Do not import feature history.

- [ ] **Step 6: Bootstrap the local Linux tree**

```bash
tools/myself_kswapd/bootstrap_linux617_l02_tree.sh \
  --source /home/lzx/Desktop/huawei/myself-kswapd-l01/Linux6.17 \
  --dest /home/lzx/Desktop/huawei/myself-kswapd-l02/Linux6.17
```

- [ ] **Step 7: Run baseline regression**

```bash
python3 -m unittest discover -s tools/myself_kswapd/tests -v
bash -n tools/myself_kswapd/capture_kswapd_trace.sh

cmake -S "用户态模拟器/v1" \
  -B /tmp/l02-task2-shadow \
  -DRECLAIM_ENABLE_TESTS=ON
cmake --build /tmp/l02-task2-shadow -j"$(nproc)"
ctest --test-dir /tmp/l02-task2-shadow --output-on-failure
```

Expected: L0.1 parser `6/6`, Shadow `25/25`.

- [ ] **Step 8: Refresh empty L0.2 patch and commit**

The L0.2 patch should be empty at this stage because the local tree equals L0.1.

Commit imported prerequisites and scripts:

```bash
git add patches/0002-linux617-myself-kswapd-l01.patch tools/myself_kswapd
git commit -m "chore: import L0.1 observer prerequisites for L0.2"
```

---

### Task 3: Define Kernel Snapshot, Key, Scope, and Request Context Types

**Files:**
- Create: `Linux6.17/mm/myself_kswapd/include/lruvec_observer.h`
- Modify: `Linux6.17/mm/myself_kswapd/include/kswapd_observer.h`
- Create: `Linux6.17/mm/myself_kswapd/tests/lruvec_observer_test.c`
- Modify: `Linux6.17/mm/myself_kswapd/tests/Makefile`
- Modify: `Linux6.17/mm/myself_kswapd/Makefile`
- Refresh: `patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch`

**Interfaces:**
- Produces: all frozen kernel enums, keys, snapshots, validity masks, and observer context.

- [ ] **Step 1: Write KUnit tests for enum values and key equality**

Tests must assert:

- mode participates in key equality;
- MEMCG `(id=0,nid=0)` is not equal to GLOBAL `(id=0,nid=0)`;
- invalid `nid < 0` is rejected except for non-lruvec request events;
- NODE and MEMCG_NODE scopes differ;
- request context initializes inactive with zero sequences.

Expected RED: symbols undefined.

- [ ] **Step 2: Implement the header types**

Add exact interfaces from the frozen section. Add field-valid bits:

```c
#define MYKS_FIELD_INACTIVE_ANON  BIT_ULL(0)
#define MYKS_FIELD_ACTIVE_ANON    BIT_ULL(1)
#define MYKS_FIELD_INACTIVE_FILE  BIT_ULL(2)
#define MYKS_FIELD_ACTIVE_FILE    BIT_ULL(3)
#define MYKS_FIELD_ISOLATED_ANON  BIT_ULL(4)
#define MYKS_FIELD_ISOLATED_FILE  BIT_ULL(5)
#define MYKS_FIELD_SCANNED_TOTAL  BIT_ULL(6)
#define MYKS_FIELD_RECLAIMED_TOTAL BIT_ULL(7)
```

Add validation bits for invalid key, unsupported config, MGLRU, invalid scope, and incarnation change.

- [ ] **Step 3: Implement pure helpers**

```c
bool myks_lruvec_key_equal(const struct myks_lruvec_key *a,
                           const struct myks_lruvec_key *b);

void myks_reclaim_ctx_reset(struct myks_reclaim_observer_ctx *ctx);

u64 myks_reclaim_ctx_next_priority(struct myks_reclaim_observer_ctx *ctx);

u64 myks_reclaim_ctx_next_scan(struct myks_reclaim_observer_ctx *ctx);
```

No Linux MM side effects.

- [ ] **Step 4: Run focused KUnit object build**

Build the test object and relevant observer objects. If the environment cannot boot KUnit, object build is still required and runtime remains NOT RUN.

- [ ] **Step 5: Refresh patch and commit**

```bash
tools/myself_kswapd/refresh_linux617_l02_patch.sh \
  --base /home/lzx/Desktop/huawei/myself-kswapd-l01/Linux6.17 \
  --current "$PWD/Linux6.17" \
  --output patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch

git add patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch
git commit -m "feat: define Linux L0.2 lruvec snapshot contract"
```

---

### Task 4: Implement `CONFIG_MEMCG` Resolver and Field Scopes

**Files:**
- Create: `Linux6.17/mm/myself_kswapd/adapter/lruvec_observer.c`
- Modify: `Linux6.17/mm/myself_kswapd/include/lruvec_observer.h`
- Modify: `Linux6.17/mm/myself_kswapd/tests/lruvec_observer_test.c`
- Refresh: `patches/0003-linux617-myself-kswapd-l02-lruvec-observer.patch`

**Interfaces:**
- Produces:
  - `myks_lruvec_resolve()`
  - `myks_lruvec_collect()`
  - exact MEMCG/GLOBAL support rules.

- [ ] **Step 1: Write resolver KUnit tests**

Test with injectable resolver ops rather than real global MM state:

- MEMCG mode with `CONFIG_MEMCG=y` returns mode, cgroup ID, CSS ID, nid, and lruvec.
- GLOBAL mode under MEMCG configuration returns `-EOPNOTSUPP`.
- MEMCG mode under stubbed `CONFIG_MEMCG=n` returns `-EOPNOTSUPP`.
- GLOBAL mode under no-MEMCG returns `pgdat->__lruvec`.
- mode difference prevents key collision.
- invalid/offline nid returns `-EINVAL` or `-ENODEV` consistently.

- [ ] **Step 2: Implement resolver wrappers**

Keep MEMCG-only dereferences inside `#ifdef CONFIG_MEMCG`.

Do not resolve cgroup path strings.

- [ ] **Step 3: Write collection tests**

Verify:

- four classic LRU values use MEMCG_NODE scope in MEMCG mode;
- four classic LRU values use NODE scope in GLOBAL mode;
- isolated values always use NODE scope;
- MEMCG mode marks isolated fields valid but not per-memcg comparable;
- `consistency=APPROXIMATE`;
- no list traversal.

- [ ] **Step 4: Implement aggregate collection**

Read:

```c
lruvec_page_state(lruvec, NR_INACTIVE_ANON)
lruvec_page_state(lruvec, NR_ACTIVE_ANON)
lruvec_page_state(lruvec, NR_INACTIVE_FILE)
lruvec_page_state(lruvec, NR_ACTIVE_FILE)
node_page_state(pgdat, NR_ISOLATED_ANON)
node_page_state(pgdat, NR_ISOLATED_FILE)
```

Never take `lru_lock` for aggregate collection.

- [ ] **Step 5: Build both MEMCG configurations**

Use two output directories. `CONFIG_MEMCG=y` and `CONFIG_MEMCG=n` must compile relevant objects.

- [ ] **Step 6: Refresh patch and commit**

Commit:

```text
feat: resolve classic lruvec identities and aggregate scopes
```

---

### Task 5: Add MGLRU Enable-Time and Runtime Guards

**Files:**
- Modify: `Linux6.17/mm/myself_kswapd/adapter/lruvec_observer.c`
- Create or modify: `Linux6.17/mm/myself_kswapd/adapter/observer_config.c`
- Modify: `Linux6.17/mm/myself_kswapd/include/lruvec_observer.h`
- Modify: `Linux6.17/mm/myself_kswapd/tests/lruvec_observer_test.c`
- Refresh patch.

**Interfaces:**
- Produces:
  - observer state machine;
  - enable-time `lru_gen_enabled()` rejection;
  - per-emission runtime guard.

- [ ] **Step 1: Write failing state-machine tests**

States:

```c
enum myks_observer_state {
    MYKS_OBSERVER_DISABLED = 0,
    MYKS_OBSERVER_ACTIVE,
    MYKS_OBSERVER_REJECTED_MGLRU,
};
```

Tests:

- enabling with MGLRU on leaves observer rejected;
- enabling with MGLRU off activates observer;
- runtime re-enable of MGLRU causes the next snapshot attempt to skip and transition to rejected;
- no classic snapshot is emitted after rejection;
- disabling clears active state but preserves counters.

- [ ] **Step 2: Implement injectable MGLRU query**

Production uses `lru_gen_enabled()`. Tests inject true/false without changing global MM behavior.

- [ ] **Step 3: Add counters**

```text
snapshot_skipped_disabled
snapshot_skipped_mglru
runtime_reject_count
last_error
```

No code attempts to write the MGLRU sysfs switch.

- [ ] **Step 4: Build with `CONFIG_LRU_GEN=n/y`**

Both compile. Runtime behavior for enabled MGLRU remains a smoke-test evidence item.

- [ ] **Step 5: Refresh patch and commit**

Commit:

```text
feat: reject classic snapshots while MGLRU is enabled
```

---

### Task 6: Generalize L0.1 Request/Boundary Context

**Files:**
- Modify: `Linux6.17/mm/myself_kswapd/include/kswapd_observer.h`
- Modify: `Linux6.17/mm/myself_kswapd/adapter/kswapd_observer.c`
- Modify: `Linux6.17/mm/vmscan.c`
- Modify: `Linux6.17/mm/myself_kswapd/tests/lruvec_observer_test.c`
- Refresh patch.

**Interfaces:**
- Produces:
  - one observer context per top-level reclaim request;
  - request, priority, and scan sequence allocation;
  - source propagation.

- [ ] **Step 1: Write pure context tests**

Cover:

- request begin assigns nonzero request ID;
- priority begin increments `priority_seq`;
- scan begin increments `scan_seq`;
- request end deactivates the context;
- nested calls reuse the active context;
- MEMCG source is not overwritten by direct-reclaim inference;
- UNKNOWN is used only when no explicit context exists.

- [ ] **Step 2: Add context to `scan_control` under config guard**

Add an embedded context or pointer with exact lifetime equal to `scan_control`.

Do not introduce a global task-to-context hash.

- [ ] **Step 3: Adapt L0.1 kswapd request hooks**

Preserve existing trace semantics while routing request IDs through the generalized context.

- [ ] **Step 4: Compile and run L0.1 parser regression**

Existing 6 parser tests must remain green.

- [ ] **Step 5: Refresh patch and commit**

Commit:

```text
refactor: share reclaim observer context across scan layers
```

---

### Task 7: Define Request and lruvec Snapshot Trace Events

**Files:**
- Create: `Linux6.17/mm/myself_kswapd/trace/lruvec_trace.h`
- Modify: `Linux6.17/mm/myself_kswapd/trace/trace.c`
- Modify existing request trace header if needed.
- Create fixtures: `tools/myself_kswapd/tests/fixtures/lruvec_snapshot.log`
- Create: `tools/myself_kswapd/parse_lruvec_trace.py`
- Create: `tools/myself_kswapd/tests/test_parse_lruvec_trace.py`
- Refresh patch.

**Interfaces:**
- Produces:
  - request events without fake lruvec keys;
  - `myself_kswapd:lruvec_snapshot`;
  - Python reference parser/validator.

- [ ] **Step 1: Write failing Python parser tests**

Fixtures must cover:

- valid SCAN_BEFORE/AFTER;
- HEARTBEAT/DEBUGFS with zero request identifiers;
- missing field;
- invalid mode/source/stage/scope;
- integer overflow;
- duplicate sequence;
- provisional gap;
- out-of-order per-CPU input merged by sequence;
- NODE isolated scope in MEMCG mode.

- [ ] **Step 2: Define trace event fields**

The snapshot event prints every canonical field as explicit key-value text. Do not print cgroup path.

- [ ] **Step 3: Implement Python parser**

Return structured dictionaries/dataclasses and specific error enum values. Continue after malformed lines.

- [ ] **Step 4: Add request/snapshot separation tests**

A request begin line without memcg/nid must parse successfully as a request event, not as a snapshot.

- [ ] **Step 5: Build trace objects and run Python tests**

- [ ] **Step 6: Refresh patch and commit**

Commit:

```text
feat: define request and lruvec snapshot trace contracts
```

---

### Task 8: Emit kswapd lruvec `SCAN_BEFORE/AFTER`

**Files:**
- Modify: `Linux6.17/mm/vmscan.c`
- Modify: `Linux6.17/mm/myself_kswapd/adapter/lruvec_observer.c`
- Modify KUnit tests.
- Refresh patch.

**Interfaces:**
- Consumes: active kswapd observer context.
- Produces: one scan sequence per actual `shrink_lruvec()` call.

- [ ] **Step 1: Write hook-level KUnit tests with fake emit ops**

Verify:

- one before and one after for each scan;
- same request/priority/scan IDs pair;
- exact lruvec key is stable across pair;
- disabled/MGLRU-rejected observer emits none;
- collection failure records an observer error but returns control to reclaim.

- [ ] **Step 2: Add the minimal hook around the canonical classic scan call**

Do not wrap MGLRU generation scan.

- [ ] **Step 3: Preserve native return values and control flow**

Observer calls must be `void` or ignored diagnostics. No branch may alter reclaim decisions.

- [ ] **Step 4: Build `mm/vmscan.o`, observer objects, and KUnit objects**

- [ ] **Step 5: Refresh patch and commit**

Commit:

```text
feat: observe kswapd classic lruvec scans
```

---

### Task 9: Add direct reclaim request boundaries

**Files:**
- Modify: `Linux6.17/mm/vmscan.c`
- Modify: observer adapter/context.
- Modify KUnit tests.
- Refresh patch.

**Interfaces:**
- Produces: DIRECT request context shared by every nested scan.

- [ ] **Step 1: Write tests for a synthetic direct request spanning multiple scans**

Expected:

```text
one request_id
multiple priority_seq values
multiple scan_seq values
source DIRECT for all scans
```

- [ ] **Step 2: Initialize context only at the top-level direct reclaim entry**

Use the actual Linux 6.17 call graph found in the local source. Do not infer source again in `shrink_lruvec()`.

- [ ] **Step 3: End the request on every top-level exit path**

Use a single cleanup label when practical. Observer cleanup must not change native return code.

- [ ] **Step 4: Build and run parser regression**

- [ ] **Step 5: Refresh patch and commit**

Commit:

```text
feat: observe direct reclaim request and lruvec scans
```

---

### Task 10: Add memcg reclaim source propagation and deduplication

**Files:**
- Modify: `Linux6.17/mm/vmscan.c`
- Modify: observer context code.
- Modify KUnit tests.
- Refresh patch.

**Interfaces:**
- Produces: MEMCG request context that remains MEMCG through nested reclaim calls.

- [ ] **Step 1: Write nested-context tests**

Verify:

- top-level memcg request creates one request ID;
- nested direct-style helpers reuse it;
- source remains MEMCG;
- no duplicate request_begin/request_end;
- multiple lruvec scans receive unique scan sequences.

- [ ] **Step 2: Initialize MEMCG context at the actual explicit memcg reclaim entry**

Use local Linux 6.17 source evidence.

- [ ] **Step 3: Guard against reinitializing an already active context**

- [ ] **Step 4: Build objects and run tests**

- [ ] **Step 5: Refresh patch and commit**

Commit:

```text
feat: observe memcg reclaim without nested request duplication
```

---

### Task 11: Implement debugfs status, config, and one-shot aggregate snapshot

**Files:**
- Create: `Linux6.17/mm/myself_kswapd/debugfs/lruvec_debugfs.c`
- Modify: Kconfig/Makefile/header.
- Modify KUnit tests.
- Refresh patch.

**Interfaces:**
- Produces:
  - `observer_status`
  - `observer_config`
  - `snapshot`
  - immutable per-open snapshot buffer.

- [ ] **Step 1: Write config parser tests**

Cover:

- valid key/value set;
- unknown key;
- invalid integer;
- invalid mode under current config;
- heartbeat below 1000ms;
- heartbeat with no filter;
- sample limit > 32;
- max entries/bytes zero or overflow;
- failed update leaves previous config unchanged.

- [ ] **Step 2: Implement copy-validate-swap config**

Readers see an immutable config snapshot. No partial update.

- [ ] **Step 3: Write per-open snapshot tests**

Use test ops to count collection calls:

- one `open()` causes one collection;
- multiple `read()` calls do not recollect;
- status read causes zero collection;
- bounded output sets `nr_total`, `nr_emitted`, `truncated`.

- [ ] **Step 4: Implement `seq_file`/private-buffer lifecycle**

No LRU lock is held while formatting.

- [ ] **Step 5: Build with DEBUG_FS enabled and disabled**

Disabled stubs must compile.

- [ ] **Step 6: Refresh patch and commit**

Commit:

```text
feat: add bounded debugfs lruvec snapshots
```

---

### Task 12: Implement bounded folio sample and cached `samples`

**Files:**
- Create or extend: `Linux6.17/mm/myself_kswapd/adapter/lruvec_sample.c`
- Modify debugfs code/header/tests.
- Refresh patch.

**Interfaces:**
- Produces:
  - at most 32 samples per classic LRU;
  - sample generation and cached output;
  - no sampling from `samples` reads.

- [ ] **Step 1: Write bounded-sample tests with fake list entries**

Cover:

- sample disabled;
- limit 0;
- limit 1;
- limit 32;
- limit 33 rejected;
- each of four LRU lists has independent bound;
- isolated/unevictable not sampled;
- emitted/truncated counters correct;
- `samples` read does not invoke collector.

- [ ] **Step 2: Implement fixed-capacity sample buffer**

Allocate before taking `lru_lock`. Under lock, copy only:

```text
pfn
memcg_id
nid
lru type
flags summary
```

- [ ] **Step 3: Add lock assertions/tests where available**

Formatting and user copy occur after unlock.

- [ ] **Step 4: Refresh patch and commit**

Commit:

```text
feat: add bounded debug folio samples
```

---

### Task 13: Implement filtered heartbeat

**Files:**
- Modify: debugfs/config code.
- Create or modify: `heartbeat.c`.
- Modify tests.
- Refresh patch.

**Interfaces:**
- Produces: delayed work that collects only filtered targets.

- [ ] **Step 1: Write state transition tests**

Cover:

- default disabled;
- enable with explicit memcg filter;
- enable with explicit nid filter;
- reject no-filter heartbeat;
- disable cancels pending work;
- config generation change makes stale work exit;
- MGLRU runtime rejection stops emission.

- [ ] **Step 2: Implement delayed work**

No full-system unfiltered enumeration.

- [ ] **Step 3: Build and refresh patch**

Commit:

```text
feat: add filtered lruvec observer heartbeat
```

---

### Task 14: Add the User-Space Snapshot Model and Trace Parser

**Files:**
- Create: `用户态模拟器/v1/include/myself_kswapd/kernel_lruvec_snapshot.h`
- Create: `用户态模拟器/v1/src/l02/lruvec_trace_parser.c`
- Create: `用户态模拟器/v1/tests/unit/test_lruvec_trace_parser.c`
- Modify: CMake.

**Interfaces:**
- Produces:

```c
enum kernel_lruvec_parse_status {
    KERNEL_LRUVEC_PARSE_OK = 0,
    KERNEL_LRUVEC_PARSE_NOT_LRUVEC_EVENT,
    KERNEL_LRUVEC_PARSE_MISSING_FIELD,
    KERNEL_LRUVEC_PARSE_INVALID_INTEGER,
    KERNEL_LRUVEC_PARSE_INVALID_ENUM,
    KERNEL_LRUVEC_PARSE_OVERFLOW,
    KERNEL_LRUVEC_PARSE_INVALID_KEY,
    KERNEL_LRUVEC_PARSE_INVALID_SCOPE,
};

int kernel_lruvec_parse_trace_line(
    const char *line,
    struct kernel_lruvec_snapshot *out,
    struct kernel_lruvec_parse_error *error);
```

- [ ] **Step 1: Write C parser tests mirroring Python fixtures**

Every canonical field and error case must be covered.

- [ ] **Step 2: Implement strict integer parsing**

Use `strtoull`/`strtol` with errno, end-pointer, range, and duplicate-field checks.

- [ ] **Step 3: Verify C and Python parsers agree**

Create a fixture-driven comparison test or script.

- [ ] **Step 4: Commit**

```text
feat: parse Linux lruvec snapshots in user space
```

---

### Task 15: Implement the Ordered Snapshot Store

**Files:**
- Create: `用户态模拟器/v1/include/myself_kswapd/kernel_snapshot_store.h`
- Create: `用户态模拟器/v1/src/l02/kernel_snapshot_store.c`
- Create: `用户态模拟器/v1/tests/unit/test_kernel_snapshot_store.c`
- Modify: CMake.

**Interfaces:**
- Produces:

```c
enum kernel_snapshot_ingest_status {
    KERNEL_SNAPSHOT_ACCEPTED = 0,
    KERNEL_SNAPSHOT_DUPLICATE,
    KERNEL_SNAPSHOT_STALE,
    KERNEL_SNAPSHOT_PROVISIONAL_GAP,
    KERNEL_SNAPSHOT_STAGE_ORDER_ERROR,
    KERNEL_SNAPSHOT_INCARCATION_CHANGED,
};

int kernel_snapshot_store_ingest(
    struct kernel_snapshot_store *store,
    const struct kernel_lruvec_snapshot *snapshot,
    struct kernel_snapshot_ingest_result *result);

int kernel_snapshot_store_get_latest(
    const struct kernel_snapshot_store *store,
    const struct kernel_lruvec_key *key,
    struct kernel_lruvec_snapshot *out);
```

- [ ] **Step 1: Write tests**

Cover duplicate, stale, gap, different mode, different memcg, different nid, request interleaving, scan before/after pairing, and CSS incarnation change.

- [ ] **Step 2: Implement a sparse hash keyed by `(mode,memcg_id,nid)`**

No fixed node array.

- [ ] **Step 3: Preserve the newest accepted snapshot**

Stale and duplicate records never overwrite it.

- [ ] **Step 4: Commit**

```text
feat: store ordered lruvec observations
```

---

### Task 16: Add Bootstrap Aggregate Diagnostics

**Files:**
- Create: `用户态模拟器/v1/src/l02/bootstrap_aggregate.c`
- Extend: `kernel_snapshot_store.h`
- Extend tests.

**Interfaces:**
- Produces an independent kernel aggregate baseline, not Shadow state.

- [ ] **Step 1: Write isolation tests**

Assert:

- bootstrap ingest creates no Shadow page/domain/lruvec;
- Shadow candidate counts do not change;
- bootstrap and strict modes have distinct status/output;
- latest baseline follows store ordering rules.

- [ ] **Step 2: Implement baseline API**

```c
int kernel_bootstrap_aggregate_update(
    struct kernel_bootstrap_aggregate *baseline,
    const struct kernel_lruvec_snapshot *snapshot);
```

- [ ] **Step 3: Commit**

```text
feat: add kernel aggregate bootstrap diagnostics
```

---

### Task 17: Add Read-Only Shadow Aggregate Lookup and STRICT_COMPARE

**Files:**
- Create: `用户态模拟器/v1/include/myself_kswapd/shadow_alignment.h`
- Create: `用户态模拟器/v1/src/l02/shadow_alignment.c`
- Create: `用户态模拟器/v1/tests/unit/test_shadow_alignment.c`
- Modify only if required:
  - `用户态模拟器/v1/include/myself_kswapd/shadow_lru.h`
  - `用户态模拟器/v1/src/core/shadow_lru.c`
- Modify CMake.

**Interfaces:**
- Produces:

```c
int shadow_engine_lookup_lruvec_stats(
    struct reclaim_engine *engine,
    uint64_t memcg_id,
    int nid,
    struct shadow_lruvec_stats *out);
```

This lookup must never create a domain/lruvec.

Alignment:

```c
enum shadow_alignment_status {
    SHADOW_ALIGNMENT_MATCH = 0,
    SHADOW_ALIGNMENT_COUNT_DRIFT,
    SHADOW_ALIGNMENT_MISSING_SHADOW_LRUVEC,
    SHADOW_ALIGNMENT_MISSING_KERNEL_LRUVEC,
    SHADOW_ALIGNMENT_STALE_KERNEL_SNAPSHOT,
    SHADOW_ALIGNMENT_MEMCG_INCARCATION_CHANGED,
    SHADOW_ALIGNMENT_FIELD_NOT_COMPARABLE,
    SHADOW_ALIGNMENT_UNSUPPORTED_PAGE_LEVEL_COMPARE,
    SHADOW_ALIGNMENT_UNSUPPORTED_MGLRU,
};

int shadow_alignment_compare(
    struct reclaim_engine *engine,
    const struct kernel_lruvec_snapshot *snapshot,
    struct shadow_alignment_result *result);
```

- [ ] **Step 1: Write failing non-creating lookup tests**

Lookup of a missing domain/nid must return NOT_FOUND and leave domain/lruvec counts unchanged.

- [ ] **Step 2: Implement minimal public read-only lookup**

Reuse existing refcount and lock order. Do not expose internal pointers.

- [ ] **Step 3: Write alignment tests**

Cover:

- MATCH;
- each individual count drift;
- delta direction `kernel-shadow`;
- missing Shadow;
- stale snapshot;
- MEMCG isolated is FIELD_NOT_COMPARABLE and does not turn equal four-LRU counts into COUNT_DRIFT;
- GLOBAL node isolated comparison;
- policy-like metadata does not affect physical comparison;
- no mutation before/after validator snapshot.

- [ ] **Step 4: Implement alignment**

Only physical stats.

- [ ] **Step 5: Run all Shadow tests and sanitizers**

Expected: existing 25 plus new L0.2 tests pass.

- [ ] **Step 6: Commit**

```text
feat: compare kernel and Shadow physical lruvec counts
```

---

### Task 18: Add CLI and Capture Pipeline

**Files:**
- Create: `用户态模拟器/v1/tools/lruvec_observer_cli.c`
- Modify CMake.
- Modify: `tools/myself_kswapd/capture_kswapd_trace.sh`
- Create: `tools/myself_kswapd/capture_lruvec_trace.sh`
- Create integration test.

**Interfaces:**
- Produces CLI modes:
  - `strict`
  - `bootstrap`
  - `parse-only`

- [ ] **Step 1: Write CLI integration test with fixture input**

Assert deterministic JSONL or TSV output for MATCH, DRIFT, gap, and parse error.

- [ ] **Step 2: Implement CLI**

Inputs:

```text
--input <trace file or ->
--mode strict|bootstrap|parse-only
--output jsonl|tsv
```

Strict mode requires a configured/replayed Shadow engine source; when absent, return a clear missing-Shadow status rather than creating state.

- [ ] **Step 3: Extend capture script**

Capture request and lruvec events, per-CPU overrun stats, start/end timestamps, MGLRU state, and observer config.

- [ ] **Step 4: Commit**

```text
feat: add Linux lruvec observer capture and CLI pipeline
```

---

### Task 19: Full Build Matrix, Sanitizers, and Failure Evidence

**Files:**
- Create: `tools/myself_kswapd/check_l02.sh`
- Create: `docs/reports/linux-l02-validation.md`
- Refresh final patch.

**Interfaces:**
- Produces a single reproducible validation entry point.

- [ ] **Step 1: Implement validation script**

It must run:

1. Python unit tests.
2. User-space default CMake/CTest.
3. User-space ASan/UBSan with leak detection.
4. User-space full test binary 100 times.
5. Linux object build with MEMCG=y/LRU_GEN=n.
6. Linux object build with MEMCG=n/LRU_GEN=n.
7. Linux object build with LRU_GEN=y.
8. KUnit relevant object build.
9. shell syntax checks.
10. `git diff --check`.
11. patch applicability check against the expected L0.1 tree.

- [ ] **Step 2: Run the script from a clean worktree**

Record exact commands, exit codes, test counts, and elapsed times.

- [ ] **Step 3: Retry TSan honestly**

If the same `unexpected memory mapping` occurs before tests, record:

```text
NOT RUN / ENVIRONMENT BLOCKED
```

Do not claim pass.

- [ ] **Step 4: Refresh the final kernel patch**

Review that `0003` contains only allowlisted L0.2 paths and does not include build output.

- [ ] **Step 5: Commit**

```text
test: add Linux L0.2 validation matrix
```

---

### Task 20: Runtime Smoke or Explicit Environment Block

**Files:**
- Modify: `docs/reports/linux-l02-validation.md`
- Create: `tools/myself_kswapd/run_l02_smoke.sh`

**Interfaces:**
- Produces runtime evidence for E1–E9 or explicit blocked status.

- [ ] **Step 1: Write a preflight script**

Check:

- booted kernel identity;
- debugfs/tracefs mounted;
- root privileges;
- classic LRU active;
- observer events available;
- disposable memcg support;
- tools available.

The script must stop before modifying MGLRU unless `--allow-disable-mglru` is explicitly provided.

- [ ] **Step 2: When environment is available, run smoke**

Collect:

- cgroup ID/CSS incarnation behavior;
- kswapd scan;
- direct reclaim scan;
- memcg reclaim scan;
- trace sequence;
- tracefs overrun evidence;
- debugfs truncation;
- runtime MGLRU re-enable rejection;
- observer enabled/disabled latency comparison.

- [ ] **Step 3: When environment is unavailable, record exact blocker**

Use:

```text
NOT RUN / ENVIRONMENT BLOCKED
```

List missing boot environment or privilege. Do not fabricate runtime results.

- [ ] **Step 4: Commit evidence/report updates**

```text
test: record Linux L0.2 runtime smoke status
```

---

### Task 21: Independent Read-Only Review

**Files:**
- Create outside repo: `/home/lzx/Desktop/huawei/linux-l02-lruvec-observer-review.md`

**Interfaces:**
- Consumes: complete branch diff from `e6f9e15..HEAD`.
- Produces: merge-readiness conclusion.

- [ ] **Step 1: Verify clean state and full validation**

- [ ] **Step 2: Run a fresh read-only review**

Review:

- observe-only property;
- request/priority/scan pairing;
- source deduplication;
- MEMCG/GLOBAL build boundary;
- isolated scope;
- MGLRU guards;
- trace gap claims;
- debugfs one-open/one-collection;
- sample lock scope;
- memcg/CSS lifetime;
- error paths;
- Shadow non-mutation;
- policy/physical separation;
- patch reproducibility;
- test quality.

- [ ] **Step 3: Classify findings**

Only:

```text
Critical
Important
Minor
```

Final conclusion:

```text
READY TO MERGE
READY AFTER MINOR FIXES
NOT READY — IMPORTANT ISSUES
NOT READY — CRITICAL ISSUES
```

- [ ] **Step 4: Do not merge or push**

Leave all branches/worktrees intact.

---

## Final Verification Checklist

- [ ] Approved v2 spec committed.
- [ ] This implementation plan committed.
- [ ] L0.1 prerequisites imported selectively.
- [ ] L0.1 original worktree unchanged.
- [ ] `0002` baseline patch tracked.
- [ ] `0003` L0.2 patch reproducible and allowlisted.
- [ ] MEMCG and GLOBAL formal key includes mode.
- [ ] MEMCG=y forbids fake GLOBAL mode.
- [ ] MEMCG=n compiles GLOBAL mode.
- [ ] MGLRU enable/runtime guards implemented.
- [ ] request/priority/scan hierarchy implemented.
- [ ] kswapd/direct/memcg sources implemented without duplicate request IDs.
- [ ] request and snapshot trace events separated.
- [ ] node-scope isolated semantics preserved.
- [ ] debugfs one-open/one-collection verified.
- [ ] cached samples verified.
- [ ] heartbeat filtered and bounded.
- [ ] parser/store/bootstrap/alignment implemented.
- [ ] alignment does not mutate Shadow.
- [ ] policy does not affect physical MATCH.
- [ ] default tests pass.
- [ ] 100-run repetition passes.
- [ ] ASan/UBSan pass.
- [ ] TSan status reported honestly.
- [ ] kernel build matrix passes.
- [ ] runtime smoke completed or explicitly blocked.
- [ ] independent review completed.
- [ ] no push.
- [ ] no merge to main.
- [ ] worktree clean.

## Execution Handoff

Use **Subagent-Driven Development** for implementation:

1. A fresh implementation subagent performs one task.
2. A spec-review subagent checks that task against this plan.
3. A code-quality reviewer checks correctness, locking, error handling, and test quality.
4. Critical/Important findings are fixed before the next task.
5. Each task is committed separately.
6. After Task 21, stop and report; do not merge or push.
