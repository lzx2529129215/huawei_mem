#!/usr/bin/env python3
"""Train the WhatsNextApp paper-best bidirectional LSTM next-app model."""

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
    raise SystemExit("PyTorch is required. Install torch before training app_lstm_next.") from exc

from app_lstm_next.models.app_lstm_next import AppLSTMNext


MODEL_NAME = "app_lstm_next_bidirectional"
PAD_TOKEN = "<PAD>"
UNKNOWN_TOKEN = "<UNKNOWN>"
SPECIAL_TARGET_TOKENS = {PAD_TOKEN, UNKNOWN_TOKEN, "<SOS>", "<EOS>"}

DEFAULT_DATASET_DIR = ROOT / "data" / "processed" / "app_lstm_next"
DEFAULT_APP_DATASET_DIR = ROOT / "app_lstm_next" / "data" / "processed" / "app_lstm_next"
DEFAULT_VOCAB_DIR = ROOT / "app_lstm_next" / "data" / "vocab"
DEFAULT_INPUT_VOCAB_PATH = DEFAULT_VOCAB_DIR / "input_app_vocab.json"
DEFAULT_TARGET_VOCAB_PATH = DEFAULT_VOCAB_DIR / "target_app_vocab.json"
LEGACY_VOCAB_PATH = DEFAULT_VOCAB_DIR / "app_vocab_next.json"
FALLBACK_LEGACY_VOCAB_PATH = ROOT / "data" / "vocab" / "app_vocab_next.json"
DEFAULT_CHECKPOINT_DIR = ROOT / "outputs" / "checkpoints" / "app_lstm_next"
DEFAULT_RESULTS_PATH = ROOT / "outputs" / "results" / "app_lstm_next" / "results.csv"


def load_json_vocab(path: str | Path) -> dict[str, int]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(key): int(value) for key, value in data.items()}


def write_json_if_missing(path: Path, data: dict[str, int]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"vocab saved: {path}")


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"dataset split not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def parse_time(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def sample_signature(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("user_id", ""),
        row.get("target_timestamp", ""),
        row.get("history_apps", ""),
        row.get("target_app", ""),
    )


def build_input_vocab(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(app for app in split_pipe(row.get("history_apps", "")) if app not in SPECIAL_TARGET_TOKENS)
    vocab = {PAD_TOKEN: 0, UNKNOWN_TOKEN: 1}
    for app, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        vocab.setdefault(app, len(vocab))
    return vocab


def build_target_vocab(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        target = (row.get("target_app") or "").strip()
        if target and target not in SPECIAL_TARGET_TOKENS:
            counts[target] += 1
    return {app: idx for idx, (app, _count) in enumerate(sorted(counts.items(), key=lambda item: (-item[1], item[0])))}


def resolve_input_vocab(args: argparse.Namespace, train_rows: list[dict[str, str]]) -> tuple[dict[str, int], Path]:
    requested = Path(args.app_vocab)
    candidates = [requested]
    if requested == DEFAULT_INPUT_VOCAB_PATH:
        candidates.extend([LEGACY_VOCAB_PATH, FALLBACK_LEGACY_VOCAB_PATH])
    for path in candidates:
        if path.exists():
            vocab = load_json_vocab(path)
            if path != DEFAULT_INPUT_VOCAB_PATH and requested == DEFAULT_INPUT_VOCAB_PATH:
                write_json_if_missing(DEFAULT_INPUT_VOCAB_PATH, vocab)
                return vocab, DEFAULT_INPUT_VOCAB_PATH
            return vocab, path
    vocab = build_input_vocab(train_rows)
    write_json_if_missing(requested, vocab)
    return vocab, requested


def resolve_target_vocab(args: argparse.Namespace, train_rows: list[dict[str, str]]) -> tuple[dict[str, int], Path]:
    requested = Path(args.target_app_vocab)
    if requested.exists():
        return load_json_vocab(requested), requested
    vocab = build_target_vocab(train_rows)
    write_json_if_missing(requested, vocab)
    return vocab, requested


class AppNextDataset(Dataset):
    def __init__(
        self,
        rows: list[dict[str, str]],
        input_app_vocab: dict[str, int],
        target_app_vocab: dict[str, int],
        history_len: int,
    ) -> None:
        self.rows = rows
        self.input_app_vocab = input_app_vocab
        self.target_app_vocab = target_app_vocab
        self.history_len = int(history_len)
        self.pad_id = input_app_vocab[PAD_TOKEN]
        self.unknown_id = input_app_vocab[UNKNOWN_TOKEN]
        if self.history_len <= 0:
            raise ValueError("history_len must be positive")

    def __len__(self) -> int:
        return len(self.rows)

    def input_id(self, app: str) -> int:
        return self.input_app_vocab.get(app, self.unknown_id)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        row = self.rows[idx]
        history = split_pipe(row["history_apps"])[-self.history_len :]
        if not history:
            raise ValueError("history_apps must contain at least one app")
        target_app = row["target_app"]
        if target_app not in self.target_app_vocab:
            raise KeyError(f"target_app is not in target_app_vocab: {target_app}")
        history_ids = [self.input_id(app) for app in history]
        target_id = self.target_app_vocab[target_app]
        return {
            "history_apps": torch.tensor(history_ids, dtype=torch.long),
            "lengths": torch.tensor(len(history_ids), dtype=torch.long),
            "target_app": torch.tensor(target_id, dtype=torch.long),
            "pad_id": torch.tensor(self.pad_id, dtype=torch.long),
        }


def collate_fn(batch: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
    pad_id = int(batch[0]["pad_id"].item())
    history_apps = pad_sequence(
        [item["history_apps"] for item in batch],
        batch_first=True,
        padding_value=pad_id,
    )
    lengths = torch.stack([item["lengths"] for item in batch])
    if bool((lengths <= 0).any()):
        raise ValueError("all sequence lengths must be positive")
    if int(lengths.max().item()) > history_apps.shape[1]:
        raise ValueError("lengths cannot exceed padded sequence length")
    return {
        "history_apps": history_apps,
        "lengths": lengths,
        "target_app": torch.stack([item["target_app"] for item in batch]),
    }


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def move_batch(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: value.to(device) for key, value in batch.items()}


def filter_rows_by_target(
    rows: list[dict[str, str]],
    target_app_vocab: dict[str, int],
    split: str,
) -> tuple[list[dict[str, str]], int]:
    kept: list[dict[str, str]] = []
    excluded = 0
    for row in rows:
        target = (row.get("target_app") or "").strip()
        if target in target_app_vocab and target not in SPECIAL_TARGET_TOKENS:
            kept.append(row)
        else:
            excluded += 1
    total = len(rows)
    ratio = excluded / total if total else 0.0
    print(f"{split} unknown/special target filtered: {excluded}/{total} ({ratio:.2%})")
    return kept, excluded


def validate_vocabs(input_app_vocab: dict[str, int], target_app_vocab: dict[str, int]) -> None:
    if PAD_TOKEN not in input_app_vocab or UNKNOWN_TOKEN not in input_app_vocab:
        raise ValueError("input_app_vocab must contain <PAD> and <UNKNOWN>")
    bad_targets = sorted(SPECIAL_TARGET_TOKENS & set(target_app_vocab))
    if bad_targets:
        raise ValueError(f"target_app_vocab must not contain special tokens: {bad_targets}")
    if not target_app_vocab:
        raise ValueError("target_app_vocab must contain at least one real target app")
    ids = sorted(target_app_vocab.values())
    if ids != list(range(len(ids))):
        raise ValueError("target_app_vocab ids must be contiguous from 0")


def validate_rows(
    rows: list[dict[str, str]],
    split: str,
    target_app_vocab: dict[str, int],
    history_len: int,
) -> None:
    target_counts: Counter[str] = Counter()
    duplicate_count = len(rows) - len({sample_signature(row) for row in rows})
    for line_no, row in enumerate(rows, start=2):
        user_id = (row.get("user_id") or "").strip()
        target_timestamp = (row.get("target_timestamp") or "").strip()
        if not user_id:
            raise ValueError(f"{split}:{line_no} user_id is empty")
        try:
            parse_time(target_timestamp)
        except ValueError as exc:
            raise ValueError(f"{split}:{line_no} target_timestamp is invalid: {target_timestamp}") from exc
        history = split_pipe(row.get("history_apps", ""))[-history_len:]
        if not history:
            raise ValueError(f"{split}:{line_no} history_apps is empty")
        if len(history) > history_len:
            raise ValueError(f"{split}:{line_no} history length exceeds {history_len}")
        if history[-1] == (row.get("target_app") or "").strip():
            raise ValueError(f"{split}:{line_no} last history app equals target_app")
        target = (row.get("target_app") or "").strip()
        if target in SPECIAL_TARGET_TOKENS:
            raise ValueError(f"{split}:{line_no} target_app is a special token: {target}")
        target_id = target_app_vocab.get(target)
        if target_id is None or target_id < 0 or target_id >= len(target_app_vocab):
            raise ValueError(f"{split}:{line_no} target id is out of range: {target}")
        target_counts[target] += 1
    print(f"{split} samples after filtering: {len(rows)}")
    print(f"{split} duplicate sample rows: {duplicate_count}")
    if split == "train" and any(count <= 0 for count in target_counts.values()):
        raise ValueError("each train target class must have at least one sample")


def print_dataset_checks(
    train_rows: list[dict[str, str]],
    val_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
) -> None:
    split_rows = {"train": train_rows, "val": val_rows, "test": test_rows}
    signatures = {
        split: {sample_signature(row) for row in rows}
        for split, rows in split_rows.items()
    }
    print(f"train/val duplicate overlap: {len(signatures['train'] & signatures['val'])}")
    print(f"train/test duplicate overlap: {len(signatures['train'] & signatures['test'])}")
    print(f"val/test duplicate overlap: {len(signatures['val'] & signatures['test'])}")
    if any(rows and "user_id" in rows[0] for rows in split_rows.values()):
        users = {split: {row.get("user_id", "") for row in rows if row.get("user_id", "")} for split, rows in split_rows.items()}
        for split, values in users.items():
            print(f"{split} users: {len(values)}")
        train_val_overlap = len(users["train"] & users["val"])
        train_test_overlap = len(users["train"] & users["test"])
        val_test_overlap = len(users["val"] & users["test"])
        print(f"train/val user overlap: {train_val_overlap}")
        print(f"train/test user overlap: {train_test_overlap}")
        print(f"val/test user overlap: {val_test_overlap}")
        if train_val_overlap or train_test_overlap or val_test_overlap:
            raise RuntimeError("train/val/test user splits must be disjoint")
    else:
        print("user_id columns unavailable; user split overlap cannot be checked from CSV")
    if any(rows and "target_timestamp" in rows[0] for rows in split_rows.values()):
        print("target_timestamp present; history timestamp checks require history timestamp columns")
    else:
        print("timestamp columns unavailable; future-event leakage cannot be fully checked from CSV")


def warn_meta_mismatch(dataset_meta: dict[str, Any], history_len: int, window_seconds: int) -> None:
    meta_history_len = dataset_meta.get("history_len")
    meta_window_seconds = dataset_meta.get("window_seconds", dataset_meta.get("time_window_seconds"))
    if meta_window_seconds is not None and int(meta_window_seconds) != int(window_seconds):
        print(
            "WARNING: dataset_meta window_seconds="
            f"{meta_window_seconds}, but training requested window_seconds={window_seconds}; using existing CSV rows."
        )
    if meta_history_len is not None and int(meta_history_len) != int(history_len):
        print(
            "WARNING: dataset_meta history_len="
            f"{meta_history_len}, but training requested history_len={history_len}; Dataset truncation is applied."
        )
    if meta_window_seconds is None:
        print("WARNING: dataset_meta has no window_seconds/time_window_seconds; cannot confirm 1-hour data window.")
    if meta_history_len is None:
        print("WARNING: dataset_meta has no history_len; Dataset will still keep the latest requested history_len.")


def train_one_epoch(
    model: AppLSTMNext,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    grad_clip: float,
) -> float:
    model.train()
    total_loss = 0.0
    total_samples = 0
    for batch in loader:
        batch = move_batch(batch, device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(batch["history_apps"], batch["lengths"])
        loss = criterion(logits, batch["target_app"])
        loss.backward()
        if grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        optimizer.step()
        batch_size = int(batch["target_app"].shape[0])
        total_loss += float(loss.item()) * batch_size
        total_samples += batch_size
    return total_loss / max(1, total_samples)


@torch.no_grad()
def evaluate(
    model: AppLSTMNext,
    loader: DataLoader,
    criterion: nn.Module,
    top_k: list[int],
    device: torch.device,
) -> dict[str, Any]:
    model.eval()
    hits = {k: 0 for k in top_k}
    reciprocal_rank_sum = 0.0
    total_loss = 0.0
    total = 0
    max_k = min(max(top_k), model.num_target_apps)
    for batch in loader:
        batch = move_batch(batch, device)
        logits = model(batch["history_apps"], batch["lengths"])
        loss = criterion(logits, batch["target_app"])
        ranked = torch.topk(logits, k=max_k, dim=1).indices
        targets = batch["target_app"].view(-1, 1)
        batch_size = int(targets.shape[0])
        total += batch_size
        total_loss += float(loss.item()) * batch_size
        matches = ranked.eq(targets)
        for k in top_k:
            hits[k] += int(matches[:, : min(k, max_k)].any(dim=1).sum().item())
        found = matches.nonzero(as_tuple=False)
        if found.numel() > 0:
            reciprocal_rank_sum += float((1.0 / (found[:, 1].float() + 1.0)).sum().item())
    return {
        "loss": total_loss / max(1, total),
        "recall_at": {k: hits[k] / total if total else 0.0 for k in top_k},
        "mrr": reciprocal_rank_sum / total if total else 0.0,
        "num_samples": total,
    }


def make_loader(
    rows: list[dict[str, str]],
    input_app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    history_len: int,
    batch_size: int,
    shuffle: bool,
    generator: torch.Generator | None = None,
) -> DataLoader:
    return DataLoader(
        AppNextDataset(rows, input_app_vocab, target_app_vocab, history_len),
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=collate_fn,
        generator=generator if shuffle else None,
    )


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(1, 10000):
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find unused checkpoint path for {path}")


def checkpoint_payload(
    model: AppLSTMNext,
    optimizer: torch.optim.Optimizer,
    args: argparse.Namespace,
    dataset_meta: dict[str, Any],
    input_app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    epoch: int,
    train_loss: float,
    val_metrics: dict[str, Any],
    train_samples: int,
    val_samples: int,
    test_samples: int,
    excluded_val_targets: int,
    excluded_test_targets: int,
) -> dict[str, Any]:
    return {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": epoch,
        "train_loss": train_loss,
        "val_loss": val_metrics["loss"],
        "val_recall_at_8": val_metrics["recall_at"].get(8, 0.0),
        "input_app_vocab": input_app_vocab,
        "target_app_vocab": target_app_vocab,
        "num_input_tokens": len(input_app_vocab),
        "num_target_apps": len(target_app_vocab),
        "pad_id": input_app_vocab[PAD_TOKEN],
        "embedding_dim": args.embedding_dim,
        "hidden_dim": args.hidden_dim,
        "dropout": args.dropout,
        "history_len": args.history_len,
        "window_seconds": args.window_seconds,
        "batch_size": args.batch_size,
        "epochs": args.epochs,
        "learning_rate": args.lr,
        "dataset_meta": dataset_meta,
        "train_samples": train_samples,
        "val_samples": val_samples,
        "test_samples": test_samples,
        "excluded_val_targets": excluded_val_targets,
        "excluded_test_targets": excluded_test_targets,
        "seed": args.seed,
        "command_line_args": sys.argv[:],
    }


def result_rows_for_metrics(
    split: str,
    checkpoint_type: str,
    metrics: dict[str, Any],
    args: argparse.Namespace,
    input_app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    excluded_target_samples: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for k in args.top_k:
        rows.append(
            {
                "model": MODEL_NAME,
                "split": split,
                "checkpoint_type": checkpoint_type,
                "k": k,
                "recall_at_k": metrics["recall_at"][k],
                "num_samples": metrics["num_samples"],
                "num_input_tokens": len(input_app_vocab),
                "num_target_apps": len(target_app_vocab),
                "history_len": args.history_len,
                "window_seconds": args.window_seconds,
                "embedding_dim": args.embedding_dim,
                "hidden_dim": args.hidden_dim,
                "dropout": args.dropout,
                "batch_size": args.batch_size,
                "epochs": args.epochs,
                "learning_rate": args.lr,
                "seed": args.seed,
                "excluded_target_samples": excluded_target_samples,
                "loss": metrics["loss"],
                "mrr": metrics["mrr"],
            }
        )
    return rows


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "model",
        "split",
        "checkpoint_type",
        "k",
        "recall_at_k",
        "num_samples",
        "num_input_tokens",
        "num_target_apps",
        "history_len",
        "window_seconds",
        "embedding_dim",
        "hidden_dim",
        "dropout",
        "batch_size",
        "epochs",
        "learning_rate",
        "seed",
        "excluded_target_samples",
        "loss",
        "mrr",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def rounded_float(value: float) -> float:
    return round(float(value), 8)


@torch.no_grad()
def inference_trace_rows(
    model: AppLSTMNext,
    rows: list[dict[str, str]],
    split: str,
    phase: str,
    checkpoint_type: str,
    epoch: int | None,
    input_app_vocab: dict[str, int],
    target_app_vocab: dict[str, int],
    history_len: int,
    top_k: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    unknown_id = input_app_vocab[UNKNOWN_TOKEN]
    id_to_target = {idx: app for app, idx in target_app_vocab.items()}
    max_k = min(top_k, len(target_app_vocab))
    trace_rows: list[dict[str, Any]] = []
    for sample_index, row in enumerate(rows):
        history = split_pipe(row["history_apps"])[-history_len:]
        history_ids = [input_app_vocab.get(app, unknown_id) for app in history]
        target_app = row["target_app"]
        target_id = target_app_vocab[target_app]
        history_tensor = torch.tensor([history_ids], dtype=torch.long, device=device)
        lengths = torch.tensor([len(history_ids)], dtype=torch.long, device=device)
        logits = model(history_tensor, lengths)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train WhatsNextApp bidirectional LSTM next-app model.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_APP_DATASET_DIR if DEFAULT_APP_DATASET_DIR.exists() else DEFAULT_DATASET_DIR))
    parser.add_argument("--app-vocab", default=str(DEFAULT_INPUT_VOCAB_PATH))
    parser.add_argument("--target-app-vocab", default=str(DEFAULT_TARGET_VOCAB_PATH))
    parser.add_argument("--history-len", type=int, default=23)
    parser.add_argument("--window-seconds", type=int, default=3600)
    parser.add_argument("--embedding-dim", type=int, default=64)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--top-k", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6, 7, 8])
    parser.add_argument("--grad-clip", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--checkpoint-dir", default=str(DEFAULT_CHECKPOINT_DIR))
    parser.add_argument("--last-checkpoint-name", default="app_lstm_next_bidirectional_last.pt")
    parser.add_argument("--best-checkpoint-name", default="app_lstm_next_bidirectional_best_val_recall8.pt")
    parser.add_argument("--checkpoint-name", help=argparse.SUPPRESS)
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
    if args.checkpoint_name:
        args.last_checkpoint_name = args.checkpoint_name
    if args.history_len <= 0:
        raise ValueError("history_len must be positive")
    if args.window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    if args.grad_clip < 0:
        raise ValueError("grad_clip must be non-negative")
    if args.inference_trace_top_k <= 0:
        raise ValueError("inference_trace_top_k must be positive")
    trace_path = Path(args.inference_trace_output) if args.inference_trace_output else None
    if trace_path is not None:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text("", encoding="utf-8")

    set_seed(args.seed)
    dataset_dir = Path(args.dataset_dir)
    train_rows_raw = load_csv(dataset_dir / "train.csv")
    val_rows_raw = load_csv(dataset_dir / "val.csv")
    test_rows_raw = load_csv(dataset_dir / "test.csv")
    if not train_rows_raw or not test_rows_raw:
        raise ValueError("train and test splits must be non-empty")

    meta_path = dataset_dir / "dataset_meta.json"
    dataset_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    input_app_vocab, input_vocab_path = resolve_input_vocab(args, train_rows_raw)
    target_app_vocab, target_vocab_path = resolve_target_vocab(args, train_rows_raw)
    validate_vocabs(input_app_vocab, target_app_vocab)

    train_rows, excluded_train_targets = filter_rows_by_target(train_rows_raw, target_app_vocab, "train")
    val_rows, excluded_val_targets = filter_rows_by_target(val_rows_raw, target_app_vocab, "val")
    test_rows, excluded_test_targets = filter_rows_by_target(test_rows_raw, target_app_vocab, "test")
    if excluded_train_targets:
        print(f"WARNING: train targets filtered: {excluded_train_targets}; check target vocab/source CSV.")
    if not train_rows or not test_rows:
        raise ValueError("train and test splits must be non-empty after target filtering")

    validate_rows(train_rows, "train", target_app_vocab, args.history_len)
    if val_rows:
        validate_rows(val_rows, "val", target_app_vocab, args.history_len)
    validate_rows(test_rows, "test", target_app_vocab, args.history_len)
    print_dataset_checks(train_rows, val_rows, test_rows)
    warn_meta_mismatch(dataset_meta, args.history_len, args.window_seconds)

    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)

    generator = torch.Generator()
    generator.manual_seed(args.seed)
    train_loader = make_loader(
        train_rows,
        input_app_vocab,
        target_app_vocab,
        args.history_len,
        args.batch_size,
        shuffle=True,
        generator=generator,
    )
    val_loader = (
        make_loader(val_rows, input_app_vocab, target_app_vocab, args.history_len, args.batch_size, shuffle=False)
        if val_rows
        else None
    )
    test_loader = make_loader(test_rows, input_app_vocab, target_app_vocab, args.history_len, args.batch_size, shuffle=False)

    model = AppLSTMNext(
        num_input_tokens=len(input_app_vocab),
        num_target_apps=len(target_app_vocab),
        pad_id=input_app_vocab[PAD_TOKEN],
        embedding_dim=args.embedding_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
    ).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    print("model = Bidirectional LSTM")
    print(f"embedding_dim={args.embedding_dim}")
    print(f"hidden_dim per direction={args.hidden_dim}")
    print(f"bidirectional output dimension={args.hidden_dim * 2}")
    print(f"history_len={args.history_len}")
    print(f"window_seconds={args.window_seconds}")
    print(f"dropout={args.dropout}")
    print(f"epochs={args.epochs}")
    print(f"batch_size={args.batch_size}")
    print(f"learning_rate={args.lr}")
    print(f"num_input_tokens={len(input_app_vocab)}")
    print(f"num_target_apps={len(target_app_vocab)}")
    print(f"train/val/test samples={len(train_rows)}/{len(val_rows)}/{len(test_rows)}")
    print(f"excluded val/test targets={excluded_val_targets}/{excluded_test_targets}")
    print(f"device={device}")
    print(f"seed={args.seed}")
    print(f"input_app_vocab={input_vocab_path}")
    print(f"target_app_vocab={target_vocab_path}")
    if trace_path is not None:
        print(f"inference trace enabled: {trace_path}")
        print(f"inference trace splits={','.join(args.inference_trace_splits)} top_k={args.inference_trace_top_k}")

    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    last_checkpoint_path = unique_path(checkpoint_dir / args.last_checkpoint_name)
    best_checkpoint_path = unique_path(checkpoint_dir / args.best_checkpoint_name)

    best_val_recall8 = -1.0
    best_payload: dict[str, Any] | None = None
    last_train_loss = 0.0
    last_val_metrics = {"loss": 0.0, "recall_at": {k: 0.0 for k in args.top_k}, "mrr": 0.0, "num_samples": 0}
    for epoch in range(1, args.epochs + 1):
        last_train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device, args.grad_clip)
        if val_loader is not None:
            last_val_metrics = evaluate(model, val_loader, criterion, args.top_k, device)
        else:
            last_val_metrics = {"loss": 0.0, "recall_at": {k: 0.0 for k in args.top_k}, "mrr": 0.0, "num_samples": 0}
        val_recall8 = last_val_metrics["recall_at"].get(8, 0.0)
        print(
            f"epoch={epoch} train_loss={last_train_loss:.6f} "
            f"val_loss={last_val_metrics['loss']:.6f} "
            f"val_recall_at_1={last_val_metrics['recall_at'].get(1, 0.0):.6f} "
            f"val_recall_at_5={last_val_metrics['recall_at'].get(5, 0.0):.6f} "
            f"val_recall_at_8={val_recall8:.6f}"
        )
        if (
            trace_path is not None
            and args.trace_validation_each_epoch
            and val_rows
            and trace_split_enabled(args, "val")
        ):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    val_rows,
                    "val",
                    "epoch_validation",
                    "current",
                    epoch,
                    input_app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        if val_recall8 > best_val_recall8:
            best_val_recall8 = val_recall8
            best_payload = checkpoint_payload(
                model,
                optimizer,
                args,
                dataset_meta,
                input_app_vocab,
                target_app_vocab,
                epoch,
                last_train_loss,
                last_val_metrics,
                len(train_rows),
                len(val_rows),
                len(test_rows),
                excluded_val_targets,
                excluded_test_targets,
            )
            torch.save(best_payload, best_checkpoint_path)

    last_payload = checkpoint_payload(
        model,
        optimizer,
        args,
        dataset_meta,
        input_app_vocab,
        target_app_vocab,
        args.epochs,
        last_train_loss,
        last_val_metrics,
        len(train_rows),
        len(val_rows),
        len(test_rows),
        excluded_val_targets,
        excluded_test_targets,
    )
    torch.save(last_payload, last_checkpoint_path)
    if best_payload is None:
        torch.save(last_payload, best_checkpoint_path)

    result_rows: list[dict[str, Any]] = []
    checkpoints = [
        ("last", last_checkpoint_path),
        ("best_val_recall8", best_checkpoint_path),
    ]
    for checkpoint_type, checkpoint_path in checkpoints:
        payload = torch.load(checkpoint_path, map_location=device)
        model.load_state_dict(payload["model_state_dict"])
        if trace_path is not None and trace_split_enabled(args, "train"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    train_rows,
                    "train",
                    "final_eval",
                    checkpoint_type,
                    None,
                    input_app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        if val_loader is not None:
            val_metrics = evaluate(model, val_loader, criterion, args.top_k, device)
            result_rows.extend(
                result_rows_for_metrics(
                    "val",
                    checkpoint_type,
                    val_metrics,
                    args,
                    input_app_vocab,
                    target_app_vocab,
                    excluded_val_targets,
                )
            )
            if trace_path is not None and trace_split_enabled(args, "val"):
                append_inference_trace(
                    trace_path,
                    inference_trace_rows(
                        model,
                        val_rows,
                        "val",
                        "final_eval",
                        checkpoint_type,
                        None,
                        input_app_vocab,
                        target_app_vocab,
                        args.history_len,
                        args.inference_trace_top_k,
                        device,
                    ),
                )
        test_metrics = evaluate(model, test_loader, criterion, args.top_k, device)
        result_rows.extend(
            result_rows_for_metrics(
                "test",
                checkpoint_type,
                test_metrics,
                args,
                input_app_vocab,
                target_app_vocab,
                excluded_test_targets,
            )
        )
        if trace_path is not None and trace_split_enabled(args, "test"):
            append_inference_trace(
                trace_path,
                inference_trace_rows(
                    model,
                    test_rows,
                    "test",
                    "final_eval",
                    checkpoint_type,
                    None,
                    input_app_vocab,
                    target_app_vocab,
                    args.history_len,
                    args.inference_trace_top_k,
                    device,
                ),
            )
        print(
            f"{checkpoint_type} test "
            f"Recall@1={test_metrics['recall_at'].get(1, 0.0):.6f} "
            f"Recall@5={test_metrics['recall_at'].get(5, 0.0):.6f} "
            f"Recall@8={test_metrics['recall_at'].get(8, 0.0):.6f} "
            f"n={test_metrics['num_samples']}"
        )

    write_results(Path(args.output), result_rows)
    print(f"last checkpoint saved: {last_checkpoint_path}")
    print(f"best validation checkpoint saved: {best_checkpoint_path}")
    print(f"results saved: {args.output}")
    if trace_path is not None:
        print(f"inference trace saved: {trace_path}")


if __name__ == "__main__":
    main()
