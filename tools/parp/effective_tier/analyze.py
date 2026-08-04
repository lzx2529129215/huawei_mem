#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Offline Phase-E quality, quadrant, ablation, and latency analysis."""

from __future__ import annotations

import argparse
import bisect
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from .contracts import (
        BASE_FEATURES,
        FEATURE_EDGES,
        LABEL_WINDOWS_NS,
        MODEL_ABLATIONS,
        PRIMARY_LABEL,
        QUADRANTS,
        SPLITS,
        ContractError,
        folio_key,
        normalized_id,
        read_jsonl,
        reject_live_path,
        session_key,
        validate_candidate,
        validate_telemetry,
        write_json,
    )
except ImportError:  # Direct execution from this directory.
    from contracts import (  # type: ignore
        BASE_FEATURES,
        FEATURE_EDGES,
        LABEL_WINDOWS_NS,
        MODEL_ABLATIONS,
        PRIMARY_LABEL,
        QUADRANTS,
        SPLITS,
        ContractError,
        folio_key,
        normalized_id,
        read_jsonl,
        reject_live_path,
        session_key,
        validate_candidate,
        validate_telemetry,
        write_json,
    )


Scored = Tuple[int, bool, int, Mapping[str, object]]


def validate_labeled(row: Mapping[str, object]) -> None:
    validate_candidate(row)
    required = (
        "quadrant", "split", "app", "workload", "mode",
        "pressure_level", "labels", "label_semantics",
        "trace_lost_measured", "trace_lost",
        "tier_gate_coverage_measured", "tier_gate_coverage_complete",
    )
    missing = [name for name in required if name not in row]
    if missing:
        raise ContractError("labeled candidate missing: %s" %
                            ", ".join(sorted(missing)))
    if row["quadrant"] not in QUADRANTS:
        raise ContractError("invalid quadrant")
    if row["split"] not in SPLITS:
        raise ContractError("invalid session split")
    if row["label_semantics"] != "FUTURE_REAL_ACCESS_NOT_REFAULT":
        raise ContractError("future access labels cannot be called refaults")
    labels = row["labels"]
    if not isinstance(labels, Mapping):
        raise ContractError("labels must be an object")
    for name, _window in LABEL_WINDOWS_NS:
        if name not in labels or labels[name] not in (True, False, None):
            raise ContractError("invalid or missing label %s" % name)
    if not isinstance(row["trace_lost_measured"], bool):
        raise ContractError("trace_lost_measured must be boolean")
    if row["trace_lost_measured"]:
        if isinstance(row["trace_lost"], bool) or not isinstance(
                row["trace_lost"], int):
            raise ContractError("measured trace_lost must be an integer")
    elif row["trace_lost"] is not None:
        raise ContractError("unmeasured trace_lost must be null")


def _label(row: Mapping[str, object], name: str) -> Optional[bool]:
    labels = row["labels"]
    assert isinstance(labels, Mapping)
    value = labels[name]
    return value if value is None else bool(value)


def _pages(row: Mapping[str, object]) -> int:
    return int(row["folio_nr_pages"])


def _rate(rows: Iterable[Mapping[str, object]], label_name: str) -> Dict[str, object]:
    positive = 0
    negative = 0
    records = 0
    for row in rows:
        value = _label(row, label_name)
        if value is None:
            continue
        records += 1
        if value:
            positive += _pages(row)
        else:
            negative += _pages(row)
    total = positive + negative
    rate = positive / total if total else None
    low, high = _wilson(positive, total)
    return {
        "known_records": records,
        "known_base_pages": total,
        "positive_base_pages": positive,
        "negative_base_pages": negative,
        "reuse_rate": rate,
        "reuse_rate_ci95": [low, high] if low is not None else None,
    }


def _wilson(positive: int, total: int) -> Tuple[Optional[float], Optional[float]]:
    if not total:
        return None, None
    z = 1.959963984540054
    p = positive / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denominator
    radius = (z * math.sqrt((p * (1.0 - p) + z * z /
                            (4.0 * total)) / total)) / denominator
    return max(0.0, centre - radius), min(1.0, centre + radius)


def quadrant_analysis(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    quadrants: Dict[str, object] = {}
    for name in QUADRANTS:
        selected = [row for row in rows if row["quadrant"] == name]
        quadrants[name] = {
            "records": len(selected),
            "base_pages": sum(_pages(row) for row in selected),
            "special_native_protect_records": sum(
                1 for row in selected if row["special_native_protect"]),
        }
    return {
        "candidate_scope": "ALL_NATIVE_TIER_GATE_FOLIOS",
        "total_records": len(rows),
        "total_base_pages": sum(_pages(row) for row in rows),
        "quadrants": quadrants,
    }


def action_analysis(rows: Sequence[Mapping[str, object]]) -> Tuple[Dict[str, object],
                                                                    Dict[str, object]]:
    upgrades = [row for row in rows
                if row["quadrant"] == "PREDICTIVE_UPGRADE"]
    keep_reclaim = [row for row in rows if row["quadrant"] == "KEEP_RECLAIM"]
    downgrades = [row for row in rows
                  if row["quadrant"] == "PREDICTIVE_DOWNGRADE"]
    keep_protect = [row for row in rows if row["quadrant"] == "KEEP_PROTECT"]
    upgrade_windows: Dict[str, object] = {}
    downgrade_windows: Dict[str, object] = {}
    for label_name, _window in LABEL_WINDOWS_NS:
        upgrade = _rate(upgrades, label_name)
        reclaim = _rate(keep_reclaim, label_name)
        downgrade = _rate(downgrades, label_name)
        protect = _rate(keep_protect, label_name)
        upgrade_rate = upgrade["reuse_rate"]
        downgrade_rate = downgrade["reuse_rate"]
        upgrade_windows[label_name] = {
            "predictive_upgrade": upgrade,
            "keep_reclaim": reclaim,
            "upgrade_hit_rate": upgrade_rate,
            "upgrade_waste_rate": (1.0 - upgrade_rate
                                   if upgrade_rate is not None else None),
            "direction_holds": (
                upgrade_rate > reclaim["reuse_rate"]
                if upgrade_rate is not None and
                reclaim["reuse_rate"] is not None else None),
        }
        downgrade_windows[label_name] = {
            "predictive_downgrade": downgrade,
            "keep_protect": protect,
            "downgrade_mistake_rate": downgrade_rate,
            "downgrade_cold_precision": (1.0 - downgrade_rate
                                          if downgrade_rate is not None
                                          else None),
            "direction_holds": (
                downgrade_rate < protect["reuse_rate"]
                if downgrade_rate is not None and
                protect["reuse_rate"] is not None else None),
        }
    primary_up = upgrade_windows[PRIMARY_LABEL]
    primary_down = downgrade_windows[PRIMARY_LABEL]
    return ({
        "label_semantics": "FUTURE_REAL_ACCESS_NOT_REFAULT",
        "primary_label": PRIMARY_LABEL,
        "windows": upgrade_windows,
        "primary": primary_up,
    }, {
        "label_semantics": "FUTURE_REAL_ACCESS_NOT_REFAULT",
        "primary_label": PRIMARY_LABEL,
        "special_native_protect_downgrades": sum(
            1 for row in downgrades if row["special_native_protect"]),
        "non_boundary_downgrades": sum(
            1 for row in downgrades
            if int(row["native_tier"]) != int(row["native_tier_idx"]) + 1),
        "windows": downgrade_windows,
        "primary": primary_down,
    })


def _feature_value(row: Mapping[str, object], name: str) -> Optional[int]:
    if name == "native_tier" or name == "native_tier_idx":
        return int(row[name])
    features = row["features"]
    assert isinstance(features, Mapping)
    value = features[name]
    return int(value) if value is not None else None


def _bin(value: int, edges: Sequence[int]) -> int:
    # Equality belongs to the lower bin, matching the kernel/Python oracle.
    return bisect.bisect_left(edges, value)


def _eligible(rows: Iterable[Mapping[str, object]], features: Sequence[str],
              split: Optional[str] = None) -> List[Mapping[str, object]]:
    result = []
    for row in rows:
        if split is not None and row["split"] != split:
            continue
        if row["mode"] != "SHADOW_EFFECTIVE_TIER":
            continue
        if _label(row, PRIMARY_LABEL) is None:
            continue
        if not row["tier_gate_coverage_complete"]:
            continue
        if any(_feature_value(row, name) is None for name in features):
            continue
        result.append(row)
    return result


def _logit(probability: float) -> float:
    clipped = min(max(probability, 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


def _train_weights(rows: Sequence[Mapping[str, object]],
                   features: Sequence[str], scale: int = 32) -> Tuple[int, List[List[int]]]:
    total = sum(_pages(row) for row in rows)
    positive = sum(_pages(row) for row in rows
                   if _label(row, PRIMARY_LABEL))
    prior = (positive + 1.0) / (total + 2.0)
    bias = int(round(scale * _logit(prior)))
    all_weights: List[List[int]] = []
    for feature in features:
        edges = FEATURE_EDGES[feature]
        counts = [[0, 0] for _index in range(len(edges) + 1)]
        for row in rows:
            value = _feature_value(row, feature)
            assert value is not None
            index = _bin(value, edges)
            pages = _pages(row)
            counts[index][1] += pages
            if _label(row, PRIMARY_LABEL):
                counts[index][0] += pages
        weights: List[int] = []
        for positives, bin_total in counts:
            probability = (positives + 2.0 * prior) / (bin_total + 2.0)
            weight = int(round(scale * (_logit(probability) - _logit(prior))))
            weights.append(min(max(weight, -32768), 32767))
        all_weights.append(weights)
    return bias, all_weights


def _score(row: Mapping[str, object], features: Sequence[str], bias: int,
           weights: Sequence[Sequence[int]]) -> int:
    result = bias
    for feature, feature_weights in zip(features, weights):
        value = _feature_value(row, feature)
        if value is None:
            raise ContractError("cannot score a missing ablation feature")
        result += int(feature_weights[_bin(value, FEATURE_EDGES[feature])])
    return result


def _scored(rows: Sequence[Mapping[str, object]], features: Sequence[str],
            bias: int, weights: Sequence[Sequence[int]]) -> List[Scored]:
    return [(_score(row, features, bias, weights),
             bool(_label(row, PRIMARY_LABEL)), _pages(row), row)
            for row in rows]


def _thresholds(validation: Sequence[Scored],
                max_cold_mistake: float = 0.10,
                hot_precision_1: float = 0.60,
                hot_precision_2: float = 0.75) -> Tuple[int, int, int, Dict[str, object]]:
    scores = sorted(set(item[0] for item in validation))
    if not scores:
        raise ContractError("threshold selection requires validation scores")

    cold = scores[0] - 1
    cold_pages = 0
    for threshold in scores:
        selected = [item for item in validation if item[0] <= threshold]
        pages = sum(item[2] for item in selected)
        mistakes = sum(item[2] for item in selected if item[1])
        if pages and mistakes / pages <= max_cold_mistake and pages >= cold_pages:
            cold = threshold
            cold_pages = pages

    def hot_threshold(target: float, lower: int) -> Tuple[int, int]:
        best = scores[-1] + 1
        best_pages = 0
        for threshold in scores:
            if threshold < lower:
                continue
            selected = [item for item in validation if item[0] >= threshold]
            pages = sum(item[2] for item in selected)
            hits = sum(item[2] for item in selected if item[1])
            if pages and hits / pages >= target and pages > best_pages:
                best = threshold
                best_pages = pages
        return best, best_pages

    hot1, hot1_pages = hot_threshold(hot_precision_1, cold + 1)
    hot2, hot2_pages = hot_threshold(hot_precision_2, hot1 + 1)
    if hot1 <= cold:
        hot1 = cold + 1
    if hot2 <= hot1:
        hot2 = hot1 + 1
    return cold, hot1, hot2, {
        "cold_max_mistake_target": max_cold_mistake,
        "hot_precision_1_target": hot_precision_1,
        "hot_precision_2_target": hot_precision_2,
        "validation_cold_selected_pages": cold_pages,
        "validation_hot_1_selected_pages": hot1_pages,
        "validation_hot_2_selected_pages": hot2_pages,
    }


def _quality(values: Sequence[Scored]) -> Dict[str, object]:
    positive = sum(item[2] for item in values if item[1])
    negative = sum(item[2] for item in values if not item[1])
    buckets = _score_buckets(values)
    reuse_rates = [item["reuse_rate"] for item in buckets
                   if item["reuse_rate"] is not None]
    violations = sum(1 for left, right in zip(reuse_rates, reuse_rates[1:])
                     if right < left)
    return {
        "records": len(values),
        "base_pages": positive + negative,
        "positive_base_pages": positive,
        "positive_rate": (positive / (positive + negative)
                          if positive + negative else None),
        "roc_auc": _roc_auc(values),
        "pr_auc_average_precision": _average_precision(values),
        "ndcg": _ndcg(values),
        "score_bucket_reuse": buckets,
        "score_bucket_monotonic_non_decreasing": (
            violations == 0 if reuse_rates else None),
        "score_bucket_monotonicity_violations": violations,
    }


def _roc_auc(values: Sequence[Scored]) -> Optional[float]:
    positive = sum(item[2] for item in values if item[1])
    negative = sum(item[2] for item in values if not item[1])
    if not positive or not negative:
        return None
    groups: DefaultDict[int, List[int]] = defaultdict(lambda: [0, 0])
    for score, label, weight, _row in values:
        groups[score][0 if label else 1] += weight
    negatives_below = 0
    favorable = 0.0
    for score in sorted(groups):
        positives, negatives = groups[score]
        favorable += positives * negatives_below + 0.5 * positives * negatives
        negatives_below += negatives
    return favorable / (positive * negative)


def _average_precision(values: Sequence[Scored]) -> Optional[float]:
    total_positive = sum(item[2] for item in values if item[1])
    if not total_positive:
        return None
    groups: DefaultDict[int, List[int]] = defaultdict(lambda: [0, 0])
    for score, label, weight, _row in values:
        groups[score][0 if label else 1] += weight
    seen = 0
    hits = 0
    result = 0.0
    for score in sorted(groups, reverse=True):
        positives, negatives = groups[score]
        seen += positives + negatives
        hits += positives
        if positives:
            result += (positives / total_positive) * (hits / seen)
    return result


def _ndcg(values: Sequence[Scored]) -> Optional[float]:
    if not values or not any(item[1] for item in values):
        return None
    ranked = sorted(values, key=lambda item: item[0], reverse=True)
    dcg = sum((weight if label else 0) / math.log2(index + 2)
              for index, (_score_value, label, weight, _row) in
              enumerate(ranked))
    ideal = sorted(values, key=lambda item: (item[1], item[2]), reverse=True)
    idcg = sum((weight if label else 0) / math.log2(index + 2)
               for index, (_score_value, label, weight, _row) in
               enumerate(ideal))
    return dcg / idcg if idcg else None


def _score_buckets(values: Sequence[Scored]) -> List[Dict[str, object]]:
    if not values:
        return []
    ordered = sorted(values, key=lambda item: item[0])
    bucket_count = min(10, len(ordered))
    result = []
    for bucket in range(bucket_count):
        start = bucket * len(ordered) // bucket_count
        end = (bucket + 1) * len(ordered) // bucket_count
        selected = ordered[start:end]
        pages = sum(item[2] for item in selected)
        hits = sum(item[2] for item in selected if item[1])
        result.append({
            "bucket": bucket,
            "score_min": min(item[0] for item in selected),
            "score_max": max(item[0] for item in selected),
            "base_pages": pages,
            "reuse_rate": hits / pages if pages else None,
        })
    return result


def _simulate_quadrant(score: int, row: Mapping[str, object], cold: int,
                       hot1: int, hot2: int, max_upgrade: int) -> str:
    native = int(row["native_tier"])
    tier_idx = int(row["native_tier_idx"])
    special = bool(row["special_native_protect"])
    if score <= cold:
        delta = -1
    elif score >= hot2:
        delta = max_upgrade
    elif score >= hot1:
        delta = 1
    else:
        delta = 0
    # First-version downgrade safety: only the tier_idx+1 boundary is mutable.
    if delta < 0 and (special or native != tier_idx + 1):
        delta = 0
    effective = min(max(native + delta, 0), 3)
    native_actual = special or native > tier_idx
    effective_actual = special or effective > tier_idx
    if not native_actual and not effective_actual:
        return "KEEP_RECLAIM"
    if not native_actual and effective_actual:
        return "PREDICTIVE_UPGRADE"
    if native_actual and effective_actual:
        return "KEEP_PROTECT"
    return "PREDICTIVE_DOWNGRADE"


def _simulation_metrics(scored: Sequence[Scored], cold: int, hot1: int,
                        hot2: int, max_upgrade: int) -> Dict[str, object]:
    copied: List[Dict[str, object]] = []
    for score, _label_value, _weight, row in scored:
        value = dict(row)
        value["quadrant"] = _simulate_quadrant(
            score, row, cold, hot1, hot2, max_upgrade)
        copied.append(value)
    up, down = action_analysis(copied)
    return {
        "max_upgrade_tiers": max_upgrade,
        "quadrants": quadrant_analysis(copied),
        "upgrade": up["primary"],
        "downgrade": down["primary"],
    }


def train_ablations(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    """Train three GLOBAL additive-table ablations using session splits."""

    result: Dict[str, object] = {
        "model_family": "GLOBAL_REUSE_MODEL",
        "app_routing_enabled": False,
        "split_unit": "session",
        "training_mode": "SHADOW_EFFECTIVE_TIER",
        "primary_label": PRIMARY_LABEL,
        "ablations": {},
    }
    ablations = result["ablations"]
    assert isinstance(ablations, dict)
    for ablation_id, feature_tuple in MODEL_ABLATIONS:
        train = _eligible(rows, feature_tuple, "train")
        validation = _eligible(rows, feature_tuple, "validation")
        test = _eligible(rows, feature_tuple, "test")
        if not train:
            ablations[ablation_id] = {
                "status": "INSUFFICIENT_TRAIN_SESSIONS",
                "features": list(feature_tuple),
            }
            continue
        if not validation:
            ablations[ablation_id] = {
                "status": "INSUFFICIENT_VALIDATION_SESSIONS",
                "features": list(feature_tuple),
            }
            continue
        if not test:
            ablations[ablation_id] = {
                "status": "INSUFFICIENT_TEST_SESSIONS",
                "features": list(feature_tuple),
            }
            continue
        bias, weights = _train_weights(train, feature_tuple)
        threshold_scores = _scored(validation, feature_tuple,
                                   bias, weights)
        cold, hot1, hot2, selection = _thresholds(threshold_scores)
        split_quality: Dict[str, object] = {}
        scored_splits: Dict[str, List[Scored]] = {}
        for split_name, split_rows in (("train", train),
                                       ("validation", validation),
                                       ("test", test)):
            values = _scored(split_rows, feature_tuple, bias, weights)
            scored_splits[split_name] = values
            split_quality[split_name] = _quality(values)

        test_scored = scored_splits["test"]
        per_app: Dict[str, object] = {}
        per_type: Dict[str, object] = {}
        per_session: Dict[str, object] = {}
        for app in sorted(set(str(item[3]["app"]) for item in test_scored)):
            per_app[app] = _quality([item for item in test_scored
                                     if item[3]["app"] == app])
        for page_type in ("anon", "file"):
            selected = [item for item in test_scored
                        if item[3]["page_type"] == page_type]
            per_type[page_type] = _quality(selected)
        for item in test_scored:
            key = "%s/%s" % session_key(item[3])
            per_session.setdefault(key, [])
            per_session[key].append(item)  # type: ignore[union-attr]
        per_session = {key: _quality(value)  # type: ignore[arg-type]
                       for key, value in per_session.items()}

        evaluated = test_scored or scored_splits["validation"]
        ablations[ablation_id] = {
            "status": "TRAINED_OFFLINE",
            "model_name": "GLOBAL_REUSE_MODEL",
            "features": list(feature_tuple),
            "kernel_shape_compatible_v1": len(feature_tuple) <= 6,
            "model": {
                "model_name": "GLOBAL_REUSE_MODEL",
                "model_version": 1,
                "feature_schema_version": 1,
                "bias": bias,
                "cold_threshold": cold,
                "hot_threshold_1": hot1,
                "hot_threshold_2": hot2,
                "max_upgrade_tiers": 2,
                "max_downgrade_tiers": 1,
                "bin_edges": [list(FEATURE_EDGES[name])
                              for name in feature_tuple],
                "weights": weights,
            },
            "threshold_selection": selection,
            "quality": split_quality,
            "test_stability": {
                "per_app": per_app,
                "per_page_type": per_type,
                "per_session": per_session,
            },
            "upgrade_cap_ablation": [
                _simulation_metrics(evaluated, cold, hot1, hot2, cap)
                for cap in (1, 2, 3)
            ],
        }
    return result


def _percentile(values: Sequence[int], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = percentile * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: Sequence[int]) -> Dict[str, object]:
    return {
        "samples": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "p99_9": _percentile(values, 0.999),
        "max": max(values) if values else None,
    }


def analyze_telemetry(records: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    score_groups: DefaultDict[str, List[int]] = defaultdict(list)
    lock_groups: DefaultDict[str, List[int]] = defaultdict(list)
    lock_per_second: DefaultDict[str, Dict[int, int]] = defaultdict(dict)
    reclaim_groups: DefaultDict[str, List[int]] = defaultdict(list)
    app_groups: DefaultDict[str, List[int]] = defaultdict(list)
    app_failures: Counter[str] = Counter()
    app_sessions: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    efficiency: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    vm_counters: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    trace_loss: List[Dict[str, object]] = []

    for record in records:
        validate_telemetry(record)
        kind = str(record["event_kind"])
        mode = str(record["mode"])
        if kind == "score_latency":
            key = "%s/%s" % (mode, record["component"])
            score_groups[key].append(int(record["duration_ns"]))
        elif kind == "lock_latency":
            base = "%s/%s" % (mode, record["scope"])
            for field in ("held_ns", "wait_ns", "irq_disabled_ns"):
                if record[field] is not None:
                    lock_groups[base + "/" + field].append(int(record[field]))
            second = int(record["timestamp_ns"]) // 1_000_000_000
            held = int(record["held_ns"])
            previous = lock_per_second[base].get(second)
            if previous is None or held > previous:
                lock_per_second[base][second] = held
        elif kind == "reclaim_latency":
            key = "%s/%s" % (mode, record["scope"])
            reclaim_groups[key].append(int(record["duration_ns"]))
        elif kind == "app_latency":
            key = "%s/%s/%s" % (mode, record["app"], record["operation"])
            app_groups[key].append(int(record["duration_ns"]))
            if not record["success"]:
                app_failures[key] += 1
        elif kind == "app_session_summary":
            key = "%s/%s" % (mode, record["app"])
            target = app_sessions[key]
            target["sessions"] += 1
            for field in ("total_duration_ns", "stalls", "timeouts",
                          "failures"):
                target[field] += int(record[field])
        elif kind == "reclaim_efficiency":
            target = efficiency[mode]
            for field in (
                    "scanned", "isolated", "reclaimed", "native_protected",
                    "predictive_upgraded", "predictive_downgraded", "pgscan",
                    "pgsteal", "no_progress_rounds", "priority_drops",
                    "younger_generation_moves"):
                target[field] += int(record[field])
        elif kind == "vm_counter_delta":
            vm_counters[mode][str(record["counter"])] += int(record["delta"])
        elif kind == "trace_loss":
            trace_loss.append(dict(record))

    efficiency_output: Dict[str, object] = {}
    for mode, counter in efficiency.items():
        values = dict(counter)
        values["reclaimed_per_scanned"] = (
            counter["reclaimed"] / counter["scanned"]
            if counter["scanned"] else None)
        values["reclaimed_per_isolated"] = (
            counter["reclaimed"] / counter["isolated"]
            if counter["isolated"] else None)
        efficiency_output[mode] = values
    return {
        "latency": {
            "score_and_effective_tier_ns": {
                key: _distribution(values) for key, values in score_groups.items()
            },
            "reclaim_ns": {
                key: _distribution(values) for key, values in reclaim_groups.items()
            },
        },
        "lock_latency": {
            "lru_lock_ns": {
                key: _distribution(values) for key, values in lock_groups.items()
            },
            "per_second_max_held_ns": {
                key: {
                    "distribution": _distribution(list(values.values())),
                    "seconds": [
                        {
                            "second_start_ns": second * 1_000_000_000,
                            "max_held_ns": maximum,
                        }
                        for second, maximum in sorted(values.items())
                    ],
                }
                for key, values in lock_per_second.items()
            },
        },
        "reclaim_efficiency": efficiency_output,
        "app_latency": {
            "operations": {
                key: dict(_distribution(values), failures=app_failures[key])
                for key, values in app_groups.items()
            },
            "sessions": {
                key: dict(values) for key, values in app_sessions.items()
            },
        },
        "vm_counter_deltas": {
            mode: dict(values) for mode, values in vm_counters.items()
        },
        "trace_loss": trace_loss,
    }


def dataset_stability(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    def grouped(field: str) -> Dict[str, object]:
        values: DefaultDict[str, List[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            values[str(row[field])].append(row)
        return {key: _rate(selected, PRIMARY_LABEL)
                for key, selected in sorted(values.items())}

    sessions: DefaultDict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        sessions["%s/%s" % session_key(row)].append(row)
    positive_by_app = {
        key: value["positive_base_pages"]
        for key, value in grouped("app").items()  # type: ignore[union-attr]
    }
    total_positive = sum(int(value) for value in positive_by_app.values())
    dominance = (max(positive_by_app.values()) / total_positive
                 if total_positive and positive_by_app else None)
    return {
        "primary_label": PRIMARY_LABEL,
        "per_session": {key: _rate(value, PRIMARY_LABEL)
                        for key, value in sorted(sessions.items())},
        "per_app": grouped("app"),
        "per_page_type": grouped("page_type"),
        "per_split": grouped("split"),
        "positive_base_pages_by_app": positive_by_app,
        "largest_app_positive_share": dominance,
    }


def candidate_latency(rows: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    """Summarize durations carried by every tier-gate decision record."""

    groups: DefaultDict[str, List[int]] = defaultdict(list)
    for row in rows:
        mode = str(row["mode"])
        score_ns = int(row["score_duration_ns"])
        groups[mode + "/score"].append(score_ns)
        decision_raw = row.get("decision_duration_ns")
        if isinstance(decision_raw, int) and not isinstance(decision_raw, bool):
            decision_ns = int(decision_raw)
            groups[mode + "/complete_decision"].append(decision_ns)
            groups[mode + "/non_score_decision_overhead"].append(
                max(0, decision_ns - score_ns))
    return {key: _distribution(values) for key, values in groups.items()}


def analyze(rows: Sequence[Mapping[str, object]],
            telemetry: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    for row in rows:
        validate_labeled(row)
    if not rows:
        raise ContractError("no labeled candidates were supplied")

    # Prove that every experiment/session belongs to exactly one split.
    split_by_session: Dict[Tuple[str, str], str] = {}
    for row in rows:
        key = session_key(row)
        split = str(row["split"])
        if key in split_by_session and split_by_session[key] != split:
            raise ContractError("session split leakage for %s/%s" % key)
        split_by_session[key] = split

    tier = quadrant_analysis(rows)
    upgrade, downgrade = action_analysis(rows)
    tier_by_mode: Dict[str, object] = {}
    upgrade_by_mode: Dict[str, object] = {}
    downgrade_by_mode: Dict[str, object] = {}
    for mode in sorted(set(str(row["mode"]) for row in rows)):
        selected = [row for row in rows if row["mode"] == mode]
        mode_upgrade, mode_downgrade = action_analysis(selected)
        tier_by_mode[mode] = quadrant_analysis(selected)
        upgrade_by_mode[mode] = mode_upgrade
        downgrade_by_mode[mode] = mode_downgrade
    tier["by_mode"] = tier_by_mode
    upgrade["by_mode"] = upgrade_by_mode
    downgrade["by_mode"] = downgrade_by_mode
    models = train_ablations(rows)
    observation = analyze_telemetry(telemetry)
    observation["latency"]["tier_gate_candidate_ns"] = candidate_latency(rows)
    all_trace_measured = all(bool(row["trace_lost_measured"]) for row in rows)
    trace_lost_sessions = {
        session_key(row): row["trace_lost"] for row in rows
    }
    trace_lost = (sum(int(value or 0) for value in trace_lost_sessions.values())
                  if all_trace_measured else None)
    coverage_complete = all(bool(row["tier_gate_coverage_complete"])
                            for row in rows)
    primary_up = upgrade["primary"]
    primary_down = downgrade["primary"]
    bidirectional_quality = bool(
        primary_up["direction_holds"] is True and
        primary_down["direction_holds"] is True)
    summary = {
        "status": "PARP_EFFECTIVE_TIER_OFFLINE_ANALYSIS_COMPLETE",
        "candidate_scope": "ALL_NATIVE_TIER_GATE_FOLIOS",
        "label_semantics": "FUTURE_REAL_ACCESS_NOT_REFAULT",
        "session_split_only": True,
        "sessions": len(split_by_session),
        "session_split_counts": dict(Counter(split_by_session.values())),
        "candidate_records": len(rows),
        "candidate_base_pages": sum(_pages(row) for row in rows),
        "quadrant_base_pages": {
            name: tier["quadrants"][name]["base_pages"]
            for name in QUADRANTS
        },
        "predictive_upgrade_pages": tier["quadrants"][
            "PREDICTIVE_UPGRADE"]["base_pages"],
        "predictive_downgrade_pages": tier["quadrants"][
            "PREDICTIVE_DOWNGRADE"]["base_pages"],
        "upgrade_hit_rate_1s": primary_up["upgrade_hit_rate"],
        "upgrade_waste_rate_1s": primary_up["upgrade_waste_rate"],
        "downgrade_mistake_rate_1s":
            primary_down["downgrade_mistake_rate"],
        "downgrade_cold_precision_1s":
            primary_down["downgrade_cold_precision"],
        "score_latency_ns": _distribution([
            int(row["score_duration_ns"]) for row in rows
        ]),
        "trace_lost_measured": all_trace_measured,
        "trace_lost": trace_lost,
        "tier_gate_coverage_complete": coverage_complete,
        "bidirectional_offline_direction_gate": bidirectional_quality,
        "global_model_only": True,
        "app_routing_enabled": False,
        "live_shadow_collected_by_this_tool": False,
        "protect_apply_executed_by_this_tool": False,
        "bidirectional_apply_executed_by_this_tool": False,
        "pressure_executed_by_this_tool": False,
        "next_status": "PARP_EFFECTIVE_TIER_LIVE_AUTH_REQUIRED",
    }
    return {
        "summary": summary,
        "tier_reclassification": tier,
        "upgrade_analysis": upgrade,
        "downgrade_analysis": downgrade,
        "dataset_stability": dataset_stability(rows),
        "model_quality": models,
        "observability": observation,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze an exported effective-tier dataset offline")
    parser.add_argument("--samples", required=True, type=Path,
                        help="collector labeled_candidates.jsonl")
    parser.add_argument("--telemetry", type=Path,
                        help="optional exported observability JSONL")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        paths = [args.samples, args.output_dir]
        if args.telemetry is not None:
            paths.append(args.telemetry)
        for path in paths:
            reject_live_path(path)
        rows = read_jsonl([args.samples])
        telemetry = read_jsonl([args.telemetry]) if args.telemetry else []
        result = analyze(rows, telemetry)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.output_dir / "summary.json", result["summary"])
        write_json(args.output_dir / "tier_reclassification.json",
                   result["tier_reclassification"])
        write_json(args.output_dir / "upgrade_analysis.json",
                   result["upgrade_analysis"])
        write_json(args.output_dir / "downgrade_analysis.json",
                   result["downgrade_analysis"])
        write_json(args.output_dir / "dataset_stability.json",
                   result["dataset_stability"])
        write_json(args.output_dir / "model_quality.json",
                   result["model_quality"])
        model_quality = result["model_quality"]
        assert isinstance(model_quality, Mapping)
        ablations = model_quality["ablations"]
        assert isinstance(ablations, Mapping)
        base_ablation = ablations["global_no_native_tier"]
        assert isinstance(base_ablation, Mapping)
        write_json(args.output_dir / "global_model.json", {
            "status": ("OFFLINE_CANDIDATE_NOT_LIVE_AUTHORIZED"
                       if base_ablation.get("status") == "TRAINED_OFFLINE"
                       else base_ablation.get("status")),
            "model_name": "GLOBAL_REUSE_MODEL",
            "app_routing_enabled": False,
            "selected_for_live_use": False,
            "model": base_ablation.get("model"),
            "selection_requires": [
                "complete session-split quality review",
                "live SHADOW authorization and collection",
                "lock and reclaim latency gates",
            ],
        })
        observation = result["observability"]
        assert isinstance(observation, Mapping)
        write_json(args.output_dir / "latency.json", observation["latency"])
        write_json(args.output_dir / "lock_latency.json",
                   observation["lock_latency"])
        write_json(args.output_dir / "reclaim_efficiency.json",
                   observation["reclaim_efficiency"])
        write_json(args.output_dir / "app_latency.json",
                   observation["app_latency"])
        write_json(args.output_dir / "vm_counter_deltas.json", {
            "vm_counter_deltas": observation["vm_counter_deltas"],
            "trace_loss": observation["trace_loss"],
        })
    except ContractError as exc:
        print("analyze: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
