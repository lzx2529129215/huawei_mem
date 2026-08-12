#!/usr/bin/env python3
"""Train V3-aligned next-app LSTM on app_lstm_next CSV splits."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import torch
    from torch import nn
    from torch.nn.utils.rnn import pad_sequence
    from torch.utils.data import DataLoader, Dataset
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PyTorch is required for v3_aligned training.") from exc

from v3_aligned.models.app_lstm_aligned import AppLSTMAlignedV3


MODEL_NAME = "v3_aligned_next_app"
PAD_TOKEN = "<PAD>"
UNKNOWN_TOKEN = "<UNKNOWN>"
SPECIAL_TARGET_TOKENS = {PAD_TOKEN, UNKNOWN_TOKEN, "<SOS>", "<EOS>"}
CSV_REQUIRED_FIELDS = {"user_id", "target_timestamp", "history_apps", "target_app"}
DEFAULT_DATASET_DIR = ROOT / "app_lstm_next" / "data" / "processed" / "app_lstm_next"
DEFAULT_APP_VOCAB = ROOT / "app_lstm_next" / "data" / "vocab" / "input_app_vocab.json"
DEFAULT_TARGET_VOCAB = ROOT / "app_lstm_next" / "data" / "vocab" / "target_app_vocab.json"
DEFAULT_CHECKPOINT_DIR = ROOT / "outputs" / "checkpoints" / "v3_aligned"
DEFAULT_RESULTS_PATH = ROOT / "outputs" / "results" / "v3_aligned" / "results.csv"


def load_json(path: str | Path) -> dict[str, int]:
    return {str(key): int(value) for key, value in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"app_lstm_next split not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or CSV_REQUIRED_FIELDS - set(reader.fieldnames):
            raise ValueError(f"missing required fields in {path}: {sorted(CSV_REQUIRED_FIELDS)}")
        return list(reader)


def split_pipe(value: str | None) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def parse_time(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def sample_signature(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("user_id", ""),
        row.get("target_timestamp", ""),
        row.get("history_apps", ""),
        row.get("target_app", ""),
    )


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def validate_target_vocab(target_app_vocab: dict[str, int]) -> None:
    special = SPECIAL_TARGET_TOKENS & set(target_app_vocab)
    if special:
        raise ValueError(f"target_app_vocab must not contain special tokens: {sorted(special)}")
    ids = sorted(target_app_vocab.values())
    if ids != list(range(len(ids))):
        raise ValueError("target_app_vocab ids must be contiguous from 0")


def filter_rows(
    rows: list[dict[str, str]],
    target_app_vocab: dict[str, int],
    split: str,
) -> tuple[list[dict[str, str]], Counter[str]]:
    kept: list[dict[str, str]] = []
    excluded: Counter[str] = Counter()
    for row in rows:
        target = (row.get("target_app") or "").strip()
        if target in target_app_vocab and target not in SPECIAL_TARGET_TOKENS:
            kept.append(row)
        else:
            excluded["target_not_in_vocab"] += 1
    if split == "train" and excluded:
        raise ValueError(f"train targets missing from target_app_vocab: {dict(excluded)}")
    print(f"{split} target filtered: {sum(excluded.values())}/{len(rows)}")
    print(f"{split} signatures after filtering: {len({sample_signature(row) for row in kept})}")
    return kept, excluded


def validate_rows(
    rows: list[dict[str, str]],
    app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    history_len: int,
    split: str,
) -> None:
    seen_samples: set[tuple[str, str, str, str]] = set()
    user_time_counts: Counter[tuple[str, str]] = Counter()
    for line_no, row in enumerate(rows, start=2):
        user_id = (row.get("user_id") or "").strip()
        target_timestamp = (row.get("target_timestamp") or "").strip()
        history = split_pipe(row.get("history_apps"))
        target_app = (row.get("target_app") or "").strip()
        if not user_id:
            raise ValueError(f"{split}:{line_no} user_id is empty")
        try:
            parse_time(target_timestamp)
        except ValueError as exc:
            raise ValueError(f"{split}:{line_no} invalid target_timestamp: {target_timestamp}") from exc
        if not history:
            raise ValueError(f"{split}:{line_no} history_apps is empty")
        if not (1 <= len(history) <= history_len):
            raise ValueError(f"{split}:{line_no} history length out of range: {len(history)}")
        if any(history[idx] == history[idx - 1] for idx in range(1, len(history))):
            raise ValueError(f"{split}:{line_no} adjacent history apps must differ")
        if not target_app:
            raise ValueError(f"{split}:{line_no} target_app is empty")
        if target_app in SPECIAL_TARGET_TOKENS:
            raise ValueError(f"{split}:{line_no} target_app is special token: {target_app}")
        if history[-1] == target_app:
            raise ValueError(f"{split}:{line_no} last history app equals target_app")
        target_id = target_app_vocab.get(target_app)
        if target_id is None or target_id < 0 or target_id >= len(target_app_vocab):
            raise ValueError(f"{split}:{line_no} target id out of range: {target_app}")
        if PAD_TOKEN not in app_vocab or UNKNOWN_TOKEN not in app_vocab:
            raise ValueError("input app vocab must contain <PAD> and <UNKNOWN>")

        signature = sample_signature(row)
        if signature in seen_samples:
            raise ValueError(f"{split}:{line_no} duplicate complete sample: {signature}")
        seen_samples.add(signature)

        # The aligned dataset now preserves same-second ordered app switches.
        # Multiple targets can legitimately share one user_id + timestamp as
        # long as their complete sample signatures remain distinct.
        user_time_counts[(user_id, target_timestamp)] += 1
    multi_target_user_times = sum(1 for count in user_time_counts.values() if count > 1)
    print(f"{split} validated samples: {len(rows)}")
    print(f"{split} user_id + target_timestamp groups with multiple samples: {multi_target_user_times}")


def validate_user_splits(rows_by_split: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    users = {
        split: {row.get("user_id", "") for row in rows if row.get("user_id", "")}
        for split, rows in rows_by_split.items()
    }
    overlaps = {
        "train_val": len(users["train"] & users["val"]),
        "train_test": len(users["train"] & users["test"]),
        "val_test": len(users["val"] & users["test"]),
    }
    if any(overlaps.values()):
        raise RuntimeError(f"train/val/test user splits overlap: {overlaps}")
    print(f"train/val/test users: {len(users['train'])}/{len(users['val'])}/{len(users['test'])}")
    print(f"user overlaps train-val/train-test/val-test: {overlaps['train_val']}/{overlaps['train_test']}/{overlaps['val_test']}")
    return overlaps


class V3AlignedNextAppDataset(Dataset):
    def __init__(
        self,
        rows: list[dict[str, str]],
        app_vocab: dict[str, int],
        target_app_vocab: dict[str, int],
        history_len: int,
    ) -> None:
        self.rows = rows
        self.app_vocab = app_vocab
        self.target_app_vocab = target_app_vocab
        self.history_len = int(history_len)
        self.pad_id = app_vocab[PAD_TOKEN]
        self.unknown_id = app_vocab[UNKNOWN_TOKEN]

    def __len__(self) -> int:
        return len(self.rows)

    def app_id(self, app: str) -> int:
        return self.app_vocab.get(app, self.unknown_id)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        row = self.rows[idx]
        history = split_pipe(row["history_apps"])[-self.history_len :]
        if not (1 <= len(history) <= self.history_len):
            raise ValueError("history length must be between 1 and history_len")
        target_app = row["target_app"]
        if target_app not in self.target_app_vocab:
            raise KeyError(f"target_app not in shared target vocab: {target_app}")
        return {
            "user_id": row["user_id"],
            "target_timestamp": row["target_timestamp"],
            "target_app": target_app,
            "history_apps": torch.tensor([self.app_id(app) for app in history], dtype=torch.long),
            "length": len(history),
            "next_app_target": torch.tensor(self.target_app_vocab[target_app], dtype=torch.long),
        }


def make_collate_fn(pad_id: int):
    def collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        histories = [item["history_apps"] for item in batch]
        lengths = torch.tensor([item["length"] for item in batch], dtype=torch.long)
        if bool((lengths <= 0).any()):
            raise ValueError("all sequence lengths must be positive")
        history_apps = pad_sequence(histories, batch_first=True, padding_value=pad_id)
        if int(lengths.max().item()) > int(history_apps.shape[1]):
            raise ValueError("lengths cannot exceed padded sequence length")
        return {
            "user_id": [item["user_id"] for item in batch],
            "target_timestamp": [item["target_timestamp"] for item in batch],
            "target_app": [item["target_app"] for item in batch],
            "history_apps": history_apps,
            "lengths": lengths,
            "next_app_target": torch.stack([item["next_app_target"] for item in batch]),
        }

    return collate


def move_batch(batch: dict[str, Any], device: torch.device) -> dict[str, Any]:
    moved = dict(batch)
    for key in ["history_apps", "lengths", "next_app_target"]:
        moved[key] = moved[key].to(device)
    return moved


def train_one_epoch(
    model: AppLSTMAlignedV3,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    total_samples = 0
    for batch in loader:
        batch = move_batch(batch, device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(history_apps=batch["history_apps"], lengths=batch["lengths"])
        if not bool(torch.isfinite(logits).all()):
            raise RuntimeError("model logits contain NaN or Inf")
        loss = criterion(logits, batch["next_app_target"])
        loss.backward()
        optimizer.step()
        batch_size = int(batch["next_app_target"].shape[0])
        total_loss += float(loss.item()) * batch_size
        total_samples += batch_size
    return total_loss / max(1, total_samples)


@torch.no_grad()
def evaluate_next_app(
    model: AppLSTMAlignedV3,
    loader: DataLoader,
    criterion: nn.Module,
    top_k: list[int],
    device: torch.device,
) -> dict[str, Any]:
    model.eval()
    hits = {k: 0 for k in top_k}
    mrr_at_k_sum = 0.0
    total_loss = 0.0
    total = 0
    max_k = min(max(top_k), model.num_target_apps)
    for batch in loader:
        batch = move_batch(batch, device)
        logits = model(history_apps=batch["history_apps"], lengths=batch["lengths"])
        if not bool(torch.isfinite(logits).all()):
            raise RuntimeError("model logits contain NaN or Inf")
        loss = criterion(logits, batch["next_app_target"])
        ranked = torch.topk(logits, k=max_k, dim=1).indices
        targets = batch["next_app_target"].unsqueeze(1)
        matches = ranked.eq(targets)
        batch_size = int(targets.shape[0])
        total += batch_size
        total_loss += float(loss.item()) * batch_size
        for k in top_k:
            hits[k] += int(matches[:, : min(k, max_k)].any(dim=1).sum().item())
        found = matches.nonzero(as_tuple=False)
        if found.numel() > 0:
            mrr_at_k_sum += float((1.0 / (found[:, 1].float() + 1.0)).sum().item())
    return {
        "loss": total_loss / max(1, total),
        "recall_at": {k: hits[k] / total if total else 0.0 for k in top_k},
        "mrr_at_k": mrr_at_k_sum / total if total else 0.0,
        "num_samples": total,
        "mrr_k": max_k,
    }


def make_loader(
    rows: list[dict[str, str]],
    app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    history_len: int,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> DataLoader:
    generator = torch.Generator()
    generator.manual_seed(seed)
    return DataLoader(
        V3AlignedNextAppDataset(rows, app_vocab, target_app_vocab, history_len),
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=make_collate_fn(app_vocab[PAD_TOKEN]),
        generator=generator if shuffle else None,
    )


def parameter_count(model: nn.Module) -> int:
    return sum(param.numel() for param in model.parameters())


def checkpoint_payload(
    model: AppLSTMAlignedV3,
    optimizer: torch.optim.Optimizer,
    args: argparse.Namespace,
    dataset_meta: dict[str, Any],
    app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    epoch: int,
    train_loss: float,
    val_metrics: dict[str, Any],
    counts: dict[str, int],
    excluded: Counter[str],
) -> dict[str, Any]:
    return {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": epoch,
        "train_loss": train_loss,
        "val_loss": val_metrics["loss"],
        "val_recall_at_8": val_metrics["recall_at"].get(8, 0.0),
        "input_app_vocab": app_vocab,
        "target_app_vocab": target_app_vocab,
        "num_apps": len(app_vocab),
        "num_target_apps": len(target_app_vocab),
        "pad_id": app_vocab[PAD_TOKEN],
        "app_embedding_dim": args.app_embedding_dim,
        "hidden_dim": args.hidden_dim,
        "dropout": args.dropout,
        "history_len": args.history_len,
        "window_seconds": args.window_seconds,
        "batch_size": args.batch_size,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "dataset_meta": dataset_meta,
        "train_sample_count": counts["train"],
        "val_sample_count": counts["val"],
        "test_sample_count": counts["test"],
        "excluded_sample_count": sum(excluded.values()),
        "excluded_reasons": dict(excluded),
        "seed": args.seed,
        "model_parameter_count": parameter_count(model),
        "command_line_args": sys.argv[:],
    }


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "model",
        "split",
        "checkpoint_type",
        "k",
        "recall_at_k",
        "mrr_at_8",
        "num_samples",
        "num_target_apps",
        "history_len",
        "window_seconds",
        "app_embedding_dim",
        "hidden_dim",
        "dropout",
        "batch_size",
        "epochs",
        "learning_rate",
        "seed",
        "loss",
        "parameter_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rounded_float(value: float) -> float:
    return round(float(value), 8)


@torch.no_grad()
def inference_trace_rows(
    model: AppLSTMAlignedV3,
    rows: list[dict[str, str]],
    split: str,
    phase: str,
    checkpoint_type: str,
    epoch: int | None,
    app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    history_len: int,
    top_k: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    unknown_id = app_vocab[UNKNOWN_TOKEN]
    id_to_target = {idx: app for app, idx in target_app_vocab.items()}
    max_k = min(top_k, len(target_app_vocab))
    trace_rows: list[dict[str, Any]] = []
    for sample_index, row in enumerate(rows):
        history = split_pipe(row["history_apps"])[-history_len:]
        history_ids = [app_vocab.get(app, unknown_id) for app in history]
        target_app = row["target_app"]
        target_id = target_app_vocab[target_app]
        history_tensor = torch.tensor([history_ids], dtype=torch.long, device=device)
        lengths = torch.tensor([len(history_ids)], dtype=torch.long, device=device)
        logits = model(history_apps=history_tensor, lengths=lengths)
        if not bool(torch.isfinite(logits).all()):
            raise RuntimeError("model logits contain NaN or Inf")
        probabilities = torch.softmax(logits, dim=1)
        top_values, top_indices = torch.topk(probabilities, k=max_k, dim=1)
        top_target_ids = [int(idx) for idx in top_indices[0].tolist()]
        top_apps = [id_to_target[idx] for idx in top_target_ids]
        top_probabilities = [rounded_float(value) for value in top_values[0].tolist()]
        top_logits = [rounded_float(float(logits[0, idx])) for idx in top_target_ids]
        ranked_ids = torch.argsort(logits, dim=1, descending=True)[0].tolist()
        hit_rank = ranked_ids.index(target_id) + 1 if target_id in ranked_ids else ""
        trace_rows.append(
            {
                "phase": phase,
                "split": split,
                "checkpoint_type": checkpoint_type,
                "epoch": "" if epoch is None else epoch,
                "sample_index": sample_index,
                "user_id": row.get("user_id", ""),
                "target_timestamp": row.get("target_timestamp", ""),
                "history_apps": row.get("history_apps", ""),
                "history_ids": json_cell(history_ids),
                "length": len(history_ids),
                "target_app": target_app,
                "target_id": target_id,
                "predicted_app": top_apps[0] if top_apps else "",
                "predicted_target_id": top_target_ids[0] if top_target_ids else "",
                "predicted_probability": top_probabilities[0] if top_probabilities else "",
                "hit_rank": hit_rank,
                "top_k_apps": json_cell(top_apps),
                "top_k_target_ids": json_cell(top_target_ids),
                "top_k_probabilities": json_cell(top_probabilities),
                "top_k_logits": json_cell(top_logits),
                "logits": json_cell([rounded_float(value) for value in logits[0].tolist()]),
                "probabilities": json_cell([rounded_float(value) for value in probabilities[0].tolist()]),
            }
        )
    return trace_rows


def append_inference_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = [
        "phase",
        "split",
        "checkpoint_type",
        "epoch",
        "sample_index",
        "user_id",
        "target_timestamp",
        "history_apps",
        "history_ids",
        "length",
        "target_app",
        "target_id",
        "predicted_app",
        "predicted_target_id",
        "predicted_probability",
        "hit_rank",
        "top_k_apps",
        "top_k_target_ids",
        "top_k_probabilities",
        "top_k_logits",
        "logits",
        "probabilities",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def trace_split_enabled(args: argparse.Namespace, split: str) -> bool:
    return split in set(args.inference_trace_splits)


def rows_for_metrics(
    split: str,
    checkpoint_type: str,
    metrics: dict[str, Any],
    args: argparse.Namespace,
    num_target_apps: int,
    model_parameter_count: int,
) -> list[dict[str, Any]]:
    if metrics["mrr_k"] != min(8, num_target_apps):
        raise ValueError("results are expected to report MRR@8-compatible metrics")
    return [
        {
            "model": MODEL_NAME,
            "split": split,
            "checkpoint_type": checkpoint_type,
            "k": k,
            "recall_at_k": metrics["recall_at"][k],
            "mrr_at_8": metrics["mrr_at_k"],
            "num_samples": metrics["num_samples"],
            "num_target_apps": num_target_apps,
            "history_len": args.history_len,
            "window_seconds": args.window_seconds,
            "app_embedding_dim": args.app_embedding_dim,
            "hidden_dim": args.hidden_dim,
            "dropout": args.dropout,
            "batch_size": args.batch_size,
            "epochs": args.epochs,
            "learning_rate": args.lr,
            "seed": args.seed,
            "loss": metrics["loss"],
            "parameter_count": model_parameter_count,
        }
        for k in args.top_k
    ]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find unused path for {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train V3-aligned next-app LSTM on app_lstm_next data.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--app-vocab", default=str(DEFAULT_APP_VOCAB))
    parser.add_argument("--target-app-vocab", default=str(DEFAULT_TARGET_VOCAB))
    parser.add_argument("--history-len", type=int, default=23)
    parser.add_argument("--window-seconds", type=int, default=3600)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--app-embedding-dim", type=int, default=32)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--top-k", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6, 7, 8])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--checkpoint-dir", default=str(DEFAULT_CHECKPOINT_DIR))
    parser.add_argument("--last-checkpoint-name", default="v3_aligned_last.pt")
    parser.add_argument("--best-checkpoint-name", default="v3_aligned_best_val_recall8.pt")
    parser.add_argument("--output", default=str(DEFAULT_RESULTS_PATH))
    parser.add_argument(
        "--inference-trace-output",
        help="Optional CSV path for per-sample inference inputs and outputs.",
    )
    parser.add_argument(
        "--inference-trace-splits",
        nargs="+",
        choices=["train", "val", "test"],
        default=["val", "test"],
        help="Dataset splits to include in the inference trace.",
    )
    parser.add_argument(
        "--inference-trace-top-k",
        type=int,
        default=8,
        help="Number of top predictions to save per traced sample.",
    )
    parser.add_argument(
        "--trace-validation-each-epoch",
        action="store_true",
        help="Also save validation-set inference rows after each epoch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.history_len <= 0:
        raise ValueError("history_len must be positive")
    if args.window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if args.inference_trace_top_k <= 0:
        raise ValueError("inference_trace_top_k must be positive")
    trace_path = Path(args.inference_trace_output) if args.inference_trace_output else None
    if trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("", encoding="utf-8")
    set_seed(args.seed)
    app_vocab = load_json(args.app_vocab)
    target_app_vocab = load_json(args.target_app_vocab)
    validate_target_vocab(target_app_vocab)
    if PAD_TOKEN not in app_vocab or UNKNOWN_TOKEN not in app_vocab:
        raise ValueError("input app vocab must contain <PAD> and <UNKNOWN>")

    dataset_dir = Path(args.dataset_dir)
    dataset_meta_path = dataset_dir / "dataset_meta.json"
    dataset_meta = json.loads(dataset_meta_path.read_text(encoding="utf-8")) if dataset_meta_path.exists() else {}
    raw = {split: load_csv(dataset_dir / f"{split}.csv") for split in ["train", "val", "test"]}
    excluded_total: Counter[str] = Counter()
    rows: dict[str, list[dict[str, str]]] = {}
    excluded_by_split: dict[str, Counter[str]] = {}
    for split, split_rows in raw.items():
        rows[split], excluded = filter_rows(split_rows, target_app_vocab, split)
        excluded_by_split[split] = excluded
        excluded_total.update({f"{split}_{key}": value for key, value in excluded.items()})
        validate_rows(rows[split], app_vocab, target_app_vocab, args.history_len, split)
    if not rows["train"] or not rows["val"] or not rows["test"]:
        raise ValueError("train/val/test splits must be non-empty after target filtering")
    validate_user_splits(rows)

    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else ("cpu" if args.device == "auto" else args.device))
    train_loader = make_loader(rows["train"], app_vocab, target_app_vocab, args.history_len, args.batch_size, True, args.seed)
    val_loader = make_loader(rows["val"], app_vocab, target_app_vocab, args.history_len, args.batch_size, False, args.seed)
    test_loader = make_loader(rows["test"], app_vocab, target_app_vocab, args.history_len, args.batch_size, False, args.seed)

    model = AppLSTMAlignedV3(
        num_apps=len(app_vocab),
        num_target_apps=len(target_app_vocab),
        pad_id=app_vocab[PAD_TOKEN],
        app_embedding_dim=args.app_embedding_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
    ).to(device)
    model_parameter_count = parameter_count(model)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    print(f"model={MODEL_NAME}")
    print("architecture=Embedding -> single-direction LSTM -> shared Linear/ReLU/Dropout -> next_app_head")
    print(f"train/val/test samples={len(rows['train'])}/{len(rows['val'])}/{len(rows['test'])}")
    print(f"excluded val/test targets={sum(excluded_by_split['val'].values())}/{sum(excluded_by_split['test'].values())}")
    print(f"history_len={args.history_len} window_seconds={args.window_seconds}")
    print(f"app_embedding_dim={args.app_embedding_dim} hidden_dim={args.hidden_dim} dropout={args.dropout}")
    print(f"batch_size={args.batch_size} epochs={args.epochs} lr={args.lr}")
    print(f"num_apps={len(app_vocab)} num_target_apps={len(target_app_vocab)} parameters={model_parameter_count}")
    print(f"dataset_dir={dataset_dir}")
    print(f"app_vocab={args.app_vocab}")
    print(f"target_app_vocab={args.target_app_vocab}")
    print(f"device={device} seed={args.seed}")
    if trace_path is not None:
        print(f"inference trace enabled: {trace_path}")
        print(f"inference trace splits={','.join(args.inference_trace_splits)} top_k={args.inference_trace_top_k}")

    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    last_path = unique_path(checkpoint_dir / args.last_checkpoint_name)
    best_path = unique_path(checkpoint_dir / args.best_checkpoint_name)
    counts = {split: len(split_rows) for split, split_rows in rows.items()}
    best_recall8 = -1.0
    last_train_loss = 0.0
    last_val_metrics = {"loss": 0.0, "recall_at": {k: 0.0 for k in args.top_k}, "mrr_at_k": 0.0, "num_samples": 0, "mrr_k": 8}
    for epoch in range(1, args.epochs + 1):
        last_train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        last_val_metrics = evaluate_next_app(model, val_loader, criterion, args.top_k, device)
        recall8 = last_val_metrics["recall_at"].get(8, 0.0)
        print(
            f"epoch={epoch} train_loss={last_train_loss:.6f} val_loss={last_val_metrics['loss']:.6f} "
            f"val_recall_at_1={last_val_metrics['recall_at'].get(1, 0.0):.6f} "
            f"val_recall_at_5={last_val_metrics['recall_at'].get(5, 0.0):.6f} "
            f"val_recall_at_8={recall8:.6f}"
        )
        if trace_path is not None and args.trace_validation_each_epoch and trace_split_enabled(args, "val"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    rows["val"],
                    "val",
                    "epoch_validation",
                    "current",
                    epoch,
                    app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        if recall8 > best_recall8:
            best_recall8 = recall8
            torch.save(
                checkpoint_payload(
                    model,
                    optimizer,
                    args,
                    dataset_meta,
                    app_vocab,
                    target_app_vocab,
                    epoch,
                    last_train_loss,
                    last_val_metrics,
                    counts,
                    excluded_total,
                ),
                best_path,
            )

    torch.save(
        checkpoint_payload(
            model,
            optimizer,
            args,
            dataset_meta,
            app_vocab,
            target_app_vocab,
            args.epochs,
            last_train_loss,
            last_val_metrics,
            counts,
            excluded_total,
        ),
        last_path,
    )

    result_rows: list[dict[str, Any]] = []
    for checkpoint_type, path in [("last", last_path), ("best_val_recall8", best_path)]:
        payload = torch.load(path, map_location=device)
        model.load_state_dict(payload["model_state_dict"])
        if trace_path is not None and trace_split_enabled(args, "train"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    rows["train"],
                    "train",
                    "final_eval",
                    checkpoint_type,
                    None,
                    app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        val_metrics = evaluate_next_app(model, val_loader, criterion, args.top_k, device)
        if trace_path is not None and trace_split_enabled(args, "val"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    rows["val"],
                    "val",
                    "final_eval",
                    checkpoint_type,
                    None,
                    app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        test_metrics = evaluate_next_app(model, test_loader, criterion, args.top_k, device)
        if trace_path is not None and trace_split_enabled(args, "test"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    rows["test"],
                    "test",
                    "final_eval",
                    checkpoint_type,
                    None,
                    app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        result_rows.extend(rows_for_metrics("val", checkpoint_type, val_metrics, args, len(target_app_vocab), model_parameter_count))
        result_rows.extend(rows_for_metrics("test", checkpoint_type, test_metrics, args, len(target_app_vocab), model_parameter_count))
        print(
            f"{checkpoint_type} test Recall@1={test_metrics['recall_at'].get(1, 0.0):.6f} "
            f"Recall@5={test_metrics['recall_at'].get(5, 0.0):.6f} "
            f"Recall@8={test_metrics['recall_at'].get(8, 0.0):.6f} "
            f"MRR@8={test_metrics['mrr_at_k']:.6f} n={test_metrics['num_samples']}"
        )
    write_results(Path(args.output), result_rows)
    print(f"last checkpoint saved: {last_path}")
    print(f"best checkpoint saved: {best_path}")
    print(f"results saved: {args.output}")
    if trace_path is not None:
        print(f"inference trace saved: {trace_path}")


if __name__ == "__main__":
    main()
