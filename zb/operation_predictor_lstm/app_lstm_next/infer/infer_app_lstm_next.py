#!/usr/bin/env python3
"""Run single-sample next-app inference with the AppLSTMNext bidirectional LSTM."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import torch
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PyTorch is required for app_lstm_next inference.") from exc

from app_lstm_next.models.app_lstm_next import AppLSTMNext

PAD_TOKEN = "<PAD>"
UNKNOWN_TOKEN = "<UNKNOWN>"


def split_pipe(value: str | None) -> list[str]:
    """Split a pipe-separated string into a list of trimmed tokens."""
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def inverse_vocab(vocab: dict[str, int]) -> dict[int, str]:
    """Build an id→name lookup from a name→id vocabulary."""
    return {int(value): key for key, value in vocab.items()}


def pad_history(
    apps: list[str],
    input_vocab: dict[str, int],
    history_len: int,
) -> tuple[list[int], int]:
    """Map app names to ids, truncate to history_len, left-pad with PAD_TOKEN.

    Returns (padded_ids, actual_length).
    """
    if not apps:
        raise ValueError("history must contain at least one app")
    unknown_id = input_vocab[UNKNOWN_TOKEN]
    mapped = [input_vocab.get(app, unknown_id) for app in apps][-history_len:]
    actual_len = len(mapped)
    pad_count = max(0, history_len - actual_len)
    pad_id = input_vocab[PAD_TOKEN]
    return [pad_id] * pad_count + mapped, actual_len


def build_model(payload: dict[str, Any], device: torch.device) -> AppLSTMNext:
    """Reconstruct an AppLSTMNext model from a checkpoint payload."""
    model = AppLSTMNext(
        num_input_tokens=int(payload["num_input_tokens"]),
        num_target_apps=int(payload["num_target_apps"]),
        pad_id=int(payload["pad_id"]),
        embedding_dim=int(payload["embedding_dim"]),
        hidden_dim=int(payload["hidden_dim"]),
        dropout=float(payload["dropout"]),
    ).to(device)
    model.load_state_dict(payload["model_state_dict"])
    model.eval()
    return model


@torch.no_grad()
def infer(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Run single-sample inference and return top-K predictions."""
    device = torch.device(
        "cuda"
        if args.device == "auto" and torch.cuda.is_available()
        else ("cpu" if args.device == "auto" else args.device)
    )
    payload = torch.load(args.checkpoint, map_location=device)

    input_vocab: dict[str, int] = {
        str(key): int(value) for key, value in payload["input_app_vocab"].items()
    }
    target_vocab: dict[str, int] = {
        str(key): int(value) for key, value in payload["target_app_vocab"].items()
    }
    id_to_target = inverse_vocab(target_vocab)
    history_len = int(payload["history_len"])

    history_apps = split_pipe(args.history_apps)
    history_ids, length = pad_history(history_apps, input_vocab, history_len)

    batch_history = torch.tensor([history_ids], dtype=torch.long, device=device)
    batch_lengths = torch.tensor([length], dtype=torch.long, device=device)

    model = build_model(payload, device)
    logits = model(batch_history, batch_lengths)  # shape: (1, num_target_apps)

    display_scores = torch.softmax(logits, dim=1) if args.show_probabilities else logits
    k = min(args.top_k, display_scores.shape[1])
    values, indices = torch.topk(display_scores, k=k, dim=1)
    raw_logits = logits[0, indices[0]].tolist()

    rows: list[dict[str, Any]] = []
    for rank, (app_id, shown, raw_logit) in enumerate(
        zip(indices[0].tolist(), values[0].tolist(), raw_logits), start=1
    ):
        rows.append(
            {
                "rank": rank,
                "target_app_id": int(app_id),
                "app": id_to_target[int(app_id)],
                "logit": float(raw_logit),
                "probability": float(shown) if args.show_probabilities else "",
            }
        )
    return rows


def write_rows(rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    """Output results as CSV or JSON to stdout or file."""
    fields = ["rank", "target_app_id", "app", "logit", "probability"]
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"saved: {path}")
        return
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Infer Top-K next apps with AppLSTMNext (bidirectional LSTM)."
    )
    parser.add_argument("--checkpoint", required=True, help="Path to checkpoint .pt file.")
    parser.add_argument(
        "--history-apps",
        required=True,
        help="Pipe-separated foreground app history, e.g. '微信|抖音|斗鱼'.",
    )
    parser.add_argument("--top-k", type=int, default=8, help="Number of top predictions to return.")
    parser.add_argument(
        "--show-probabilities", action="store_true", help="Apply softmax to logits."
    )
    parser.add_argument(
        "--device", choices=["auto", "cpu", "cuda"], default="auto"
    )
    parser.add_argument(
        "--format", choices=["csv", "json"], default="csv", help="Output format."
    )
    parser.add_argument("--output", help="Optional output file path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_rows(infer(args), args)


if __name__ == "__main__":
    main()
