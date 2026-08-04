#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools.parp.effective_tier.analyze import analyze, analyze_telemetry
from tools.parp.effective_tier.collector import build_dataset, parse_exported_trace
from tools.parp.effective_tier.contracts import (
    BASE_FEATURES,
    ContractError,
    session_key,
    validate_access,
)
from tools.parp.effective_tier.experiment_plan import (
    build_plan,
    checklist_markdown,
    validate_manifest,
)


HERE = Path(__file__).resolve().parents[1]


def candidate(session: str, cookie: str, action: str, timestamp_ns: int,
              pages: int = 1, source_seq: int = 1) -> dict:
    decisions = {
        "KEEP_RECLAIM": (0, 0, False, False, False, 0, 0),
        "PREDICTIVE_UPGRADE": (0, 0, False, False, True, 256, 256),
        "KEEP_PROTECT": (1, 0, False, True, True, 0, 256),
        "PREDICTIVE_DOWNGRADE": (1, 0, False, True, False, -256, 0),
        "SPECIAL_NATIVE_PROTECT": (0, 0, True, False, False, 0, 0),
    }
    native, tier_idx, special, native_protect, effective_protect, delta, effective = decisions[action]
    return {
        "schema_version": 1,
        "event_kind": "tier_gate_candidate",
        "timestamp_ns": timestamp_ns,
        "experiment_id": "exp",
        "session_id": session,
        "folio_cookie": cookie,
        "folio_lifetime_epoch": 7,
        "memcg_anon_id": "memcg-1",
        "nid": 0,
        "page_type": "file" if source_seq % 2 else "anon",
        "source_seq": source_seq,
        "generation_index": 0,
        "native_tier": native,
        "native_tier_idx": tier_idx,
        "special_native_protect": special,
        "native_protect": native_protect,
        "features": {
            "time_since_last_real_access_ms": 10 + source_seq * 100,
            "previous_real_access_interval_ms": 20 + source_seq * 90,
            "reuse_interval_ema_ms": 30 + source_seq * 80,
            "consecutive_reclaim_candidate_count": source_seq % 5,
            "time_in_current_generation_ms": 40 + source_seq * 70,
            "access_ema_q8": min(255, source_seq * 20),
        },
        "reuse_score": 100 - source_seq * 10,
        "cold_threshold": -48,
        "hot_threshold_1": 48,
        "hot_threshold_2": 96,
        "delta_tier_q8": delta,
        "effective_tier_q8": effective,
        "effective_protect": effective_protect,
        "action": action,
        "bypass_reason": "NONE",
        "folio_nr_pages": pages,
        "batch_id": "batch-1",
        "reclaim_epoch": "epoch-1",
        "priority": 12,
        "score_duration_ns": 17 + source_seq,
        "actual_native_behavior": "protect" if (special or native_protect) else "reclaim",
        "isolate_result": "not_attempted" if (special or native_protect) else "succeeded",
        "reclaimed": None,
        "putback": None,
        "activated": None,
        "gate_reached": True,
        "candidate_scope": "ALL_NATIVE_TIER_GATE_FOLIOS",
    }


def access(session: str, cookie: str, timestamp_ns: int,
           lifetime: int = 7, source: str = "PTE_YOUNG") -> dict:
    return {
        "schema_version": 1,
        "event_kind": "real_access",
        "timestamp_ns": timestamp_ns,
        "experiment_id": "exp",
        "session_id": session,
        "folio_cookie": cookie,
        "folio_lifetime_epoch": lifetime,
        "access_source": source,
        "is_real_access": True,
    }


def session(session_id: str, split: str, count: int,
            end_ns: int = 10_000_000_000, lost: int = 0) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": "exp",
        "session_id": session_id,
        "app": {"train": "WPS", "validation": "FILES", "test": "QQ"}[split],
        "workload": "fixture-" + split,
        "mode": "SHADOW_EFFECTIVE_TIER",
        "pressure_level": "P2",
        "start_ns": 1,
        "observation_end_ns": end_ns,
        "split": split,
        "tier_gate_counter": {
            "measured": True,
            "source": "exported_debug_counter",
            "before": 100,
            "after": 100 + count,
            "delta": count,
        },
        "trace_loss": {
            "measured": True,
            "source": "exported_trace_per_cpu_stats",
            "before": 3,
            "after": 3 + lost,
            "lost": lost,
            "per_cpu": {"0": lost},
        },
    }


def dataset_fixture():
    actions = ["KEEP_RECLAIM", "PREDICTIVE_UPGRADE", "KEEP_PROTECT",
               "PREDICTIVE_DOWNGRADE"]
    records = []
    sessions = {}
    sequence = 1
    for split in ("train", "validation", "test"):
        session_id = "s-" + split
        sessions[("exp", session_id)] = session(session_id, split, 8)
        for repeat in range(2):
            for action_name in actions:
                cookie = "%s-%d-%s" % (split, repeat, action_name)
                timestamp = 1_000_000_000 + sequence * 10_000_000
                pages = 4 if action_name in ("PREDICTIVE_UPGRADE",
                                             "PREDICTIVE_DOWNGRADE") else 1
                records.append(candidate(session_id, cookie, action_name,
                                         timestamp, pages, sequence))
                # Make upgrades hot and downgrades cold; keep classes mixed.
                should_reuse = action_name == "PREDICTIVE_UPGRADE" or (
                    action_name == "KEEP_PROTECT" and repeat == 0) or (
                    action_name == "KEEP_RECLAIM" and repeat == 1)
                if should_reuse:
                    records.append(access(session_id, cookie,
                                          timestamp + 50_000_000))
                sequence += 1
    return records, sessions


class PhaseECollectorTests(unittest.TestCase):
    def test_exported_kernel_trace_is_normalized_offline(self):
        lines = [
            "task: parp_effective_tier_decision: time=1000000000 "
            "experiment=1 session=2 cookie=99 lifetime=7 memcg=3 nid=0 "
            "type=1 source_seq=8 gen=0 native_tier=0 tier_idx=0 special=0 "
            "native_protect=0 effective_protect=1 actual_tier_protect=0 "
            "score=100 thresholds=-48/48/96 delta_q8=256 effective_q8=256 "
            "action=1 bypass=0 pages=4 batch=11 epoch=12 priority=10 "
            "score_ns=20 decision_ns=30 sort=0 isolate_attempted=1 "
            "isolate_result=1 features=10,20,30,1,40,50 trace_lost=0",
            "task: parp_effective_tier_access: time=1050000000 cookie=99 "
            "lifetime=7 gen=0 type=1 event=0 real=1",
            "task: parp_effective_tier_access: time=1055000000 cookie=99 "
            "lifetime=7 gen=1 type=1 event=6 real=0",
            "task: parp_effective_tier_outcome: time=1060000000 cookie=99 "
            "lifetime=7 action=1 outcome=0",
            "task: parp_effective_tier_batch: time=1100000000 batch=11 "
            "epoch=12 type=1 mode=1 candidates=4 upgrades=4 downgrades=0 "
            "isolated=4 reclaimed=4 model_ns=80 lock_ns=100",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.txt"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            records, stats = parse_exported_trace([path])
        meta = session("2", "train", 1)
        meta["experiment_id"] = "1"
        labeled, telemetry, summary = build_dataset(
            records, {("1", "2"): meta})
        self.assertTrue(labeled[0]["labels"]["reuse_within_100ms"])
        self.assertTrue(labeled[0]["reclaimed"])
        self.assertEqual(stats["policy_move_access_events_ignored"], 1)
        self.assertEqual(telemetry[0]["component"], "batch_model_total")
        self.assertTrue(summary["tier_gate_coverage_complete"])

    def test_real_access_labels_lifetime_and_all_windows(self):
        row = candidate("s", "f", "PREDICTIVE_UPGRADE", 1_000_000_000)
        meta = session("s", "train", 1)
        records = [
            row,
            access("s", "f", 1_010_000_000, lifetime=8),
            access("s", "f", 1_200_000_000, lifetime=7,
                   source="MARK_ACCESSED"),
        ]
        labeled, telemetry, summary = build_dataset(records, {("exp", "s"): meta})
        labels = labeled[0]["labels"]
        self.assertFalse(labels["reuse_within_100ms"])
        self.assertTrue(labels["reuse_within_500ms"])
        self.assertTrue(labels["reuse_within_1s"])
        self.assertTrue(labels["reuse_within_5s"])
        self.assertEqual(labeled[0]["next_real_access_source"], "MARK_ACCESSED")
        self.assertEqual(summary["trace_lost"], 0)
        self.assertTrue(summary["tier_gate_coverage_complete"])
        self.assertEqual(telemetry, [])

    def test_right_censoring_is_null_not_cold(self):
        row = candidate("s", "f", "KEEP_RECLAIM", 1_000_000_000)
        meta = session("s", "train", 1, end_ns=1_250_000_000)
        labeled, _telemetry, _summary = build_dataset(
            [row], {("exp", "s"): meta})
        labels = labeled[0]["labels"]
        self.assertFalse(labels["reuse_within_100ms"])
        self.assertIsNone(labels["reuse_within_500ms"])
        self.assertIsNone(labels["reuse_within_1s"])
        self.assertIsNone(labels["reuse_within_5s"])

    def test_policy_move_cannot_be_a_real_access_label(self):
        event = access("s", "f", 123, source="NATIVE_GENERATION_MOVE")
        with self.assertRaises(ContractError):
            validate_access(event)

    def test_trace_loss_is_measured_not_inferred(self):
        row = candidate("s", "f", "KEEP_RECLAIM", 1_000_000_000)
        meta = session("s", "train", 1, lost=2)
        labeled, _telemetry, summary = build_dataset(
            [row], {("exp", "s"): meta})
        self.assertEqual(labeled[0]["trace_lost"], 2)
        self.assertFalse(labeled[0]["tier_gate_coverage_complete"])
        self.assertEqual(summary["status"],
                         "PARP_EFFECTIVE_TIER_OFFLINE_DATASET_INCOMPLETE")

    def test_special_native_protection_normalizes_to_keep_protect(self):
        row = candidate("s", "f", "SPECIAL_NATIVE_PROTECT", 1_000_000_000)
        labeled, _telemetry, _summary = build_dataset(
            [row], {("exp", "s"): session("s", "train", 1)})
        self.assertEqual(labeled[0]["quadrant"], "KEEP_PROTECT")


class PhaseEAnalysisTests(unittest.TestCase):
    def setUp(self):
        records, sessions = dataset_fixture()
        self.rows, _telemetry, _summary = build_dataset(records, sessions)

    def test_session_split_has_no_page_row_leakage(self):
        result = analyze(self.rows, [])
        self.assertTrue(result["summary"]["session_split_only"])
        seen = {}
        for row in self.rows:
            key = session_key(row)
            seen.setdefault(key, row["split"])
            self.assertEqual(seen[key], row["split"])

    def test_four_quadrants_and_page_weighted_action_metrics(self):
        result = analyze(self.rows, [])
        quadrants = result["tier_reclassification"]["quadrants"]
        self.assertEqual(set(quadrants), {
            "KEEP_RECLAIM", "PREDICTIVE_UPGRADE", "KEEP_PROTECT",
            "PREDICTIVE_DOWNGRADE",
        })
        upgrade = result["upgrade_analysis"]["primary"]
        downgrade = result["downgrade_analysis"]["primary"]
        self.assertEqual(upgrade["upgrade_hit_rate"], 1.0)
        self.assertEqual(upgrade["upgrade_waste_rate"], 0.0)
        self.assertEqual(downgrade["downgrade_mistake_rate"], 0.0)
        self.assertEqual(downgrade["downgrade_cold_precision"], 1.0)

    def test_three_global_ablations_never_route_by_app(self):
        result = analyze(self.rows, [])
        quality = result["model_quality"]
        self.assertFalse(quality["app_routing_enabled"])
        expected = {
            "global_no_native_tier",
            "global_plus_native_tier",
            "global_plus_native_tier_and_tier_idx",
        }
        self.assertEqual(set(quality["ablations"]), expected)
        prohibited = {"app", "app_id", "session_id", "workload"}
        for value in quality["ablations"].values():
            self.assertEqual(value["status"], "TRAINED_OFFLINE")
            self.assertFalse(prohibited.intersection(value["features"]))
            self.assertEqual(value["model"]["model_name"],
                             "GLOBAL_REUSE_MODEL")
            self.assertEqual(len(value["upgrade_cap_ablation"]), 3)

    def test_session_split_leakage_is_rejected(self):
        broken = deepcopy(self.rows)
        broken[1]["session_id"] = broken[0]["session_id"]
        broken[1]["split"] = "test" if broken[0]["split"] != "test" else "train"
        with self.assertRaises(ContractError):
            analyze(broken, [])

    def test_observability_latency_efficiency_and_app_schema(self):
        base = {
            "schema_version": 1,
            "timestamp_ns": 1,
            "experiment_id": "exp",
            "session_id": "s",
            "mode": "SHADOW_EFFECTIVE_TIER",
        }
        telemetry = [
            dict(base, event_kind="score_latency", component="score",
                 duration_ns=value) for value in (10, 20, 30, 40)
        ]
        telemetry.extend((
            dict(base, event_kind="lock_latency", lock_name="lru_lock",
                 scope="scan_folios", held_ns=100, wait_ns=10,
                 irq_disabled_ns=90),
            dict(base, event_kind="reclaim_latency", scope="direct_reclaim",
                 duration_ns=1000),
            dict(base, event_kind="reclaim_efficiency", scanned=100,
                 isolated=50, reclaimed=25, native_protected=10,
                 predictive_upgraded=2, predictive_downgraded=1,
                 pgscan=100, pgsteal=25, no_progress_rounds=0,
                 priority_drops=1, younger_generation_moves=2),
            dict(base, event_kind="app_latency", app="WPS", operation="save",
                 duration_ns=5000, success=False),
            dict(base, event_kind="app_session_summary", app="WPS",
                 total_duration_ns=50_000, stalls=2, timeouts=1, failures=1),
            dict(base, event_kind="vm_counter_delta",
                 counter="workingset_refault_file", delta=3),
        ))
        result = analyze_telemetry(telemetry)
        score = result["latency"]["score_and_effective_tier_ns"][
            "SHADOW_EFFECTIVE_TIER/score"]
        self.assertEqual(score["p50"], 25.0)
        efficiency = result["reclaim_efficiency"]["SHADOW_EFFECTIVE_TIER"]
        self.assertEqual(efficiency["reclaimed_per_scanned"], 0.25)
        app = result["app_latency"]["operations"][
            "SHADOW_EFFECTIVE_TIER/WPS/save"]
        self.assertEqual(app["failures"], 1)
        session_summary = result["app_latency"]["sessions"][
            "SHADOW_EFFECTIVE_TIER/WPS"]
        self.assertEqual(session_summary["timeouts"], 1)
        per_second = result["lock_latency"]["per_second_max_held_ns"][
            "SHADOW_EFFECTIVE_TIER/scan_folios"]
        self.assertEqual(per_second["seconds"][0]["max_held_ns"], 100)


class PhaseEPlanTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (HERE / "experiment_manifest.template.json").read_text(
                encoding="utf-8"))

    def test_plan_is_non_executable_and_stops_at_authorization(self):
        plan = build_plan(self.manifest)
        self.assertTrue(plan["generated_plan_only"])
        self.assertEqual(plan["runtime_actions_executed"], 0)
        self.assertEqual(plan["apply_actions_executed"], 0)
        self.assertTrue(all(cell["execution_status"] ==
                            "NOT_EXECUTED_PLAN_ONLY"
                            for cell in plan["cells"]))
        checklist = checklist_markdown(self.manifest, plan)
        self.assertIn("PARP_EFFECTIVE_TIER_LIVE_AUTH_REQUIRED", checklist)

    def test_unsafe_manifest_is_rejected(self):
        unsafe = deepcopy(self.manifest)
        unsafe["safety"]["apply_authorized"] = True
        with self.assertRaises(ContractError):
            validate_manifest(unsafe)
        unsafe = deepcopy(self.manifest)
        unsafe["command"] = "write something"
        with self.assertRaises(ContractError):
            validate_manifest(unsafe)

    def test_all_json_contracts_are_parseable(self):
        names = (
            "feature_schema.json",
            "raw_event.schema.json",
            "session_metadata.schema.json",
            "labeled_candidate.schema.json",
            "observability.schema.json",
            "experiment_manifest.schema.json",
            "experiment_manifest.template.json",
        )
        for name in names:
            with self.subTest(name=name):
                value = json.loads((HERE / name).read_text(encoding="utf-8"))
                self.assertIsInstance(value, dict)


if __name__ == "__main__":
    unittest.main()
