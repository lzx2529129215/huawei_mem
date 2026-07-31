#!/usr/bin/env python3
"""Evaluate a saved app_lstm_next bidirectional LSTM checkpoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import torch
    from torch import nn
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PyTorch is required. Install torch before evaluating app_lstm_next.") from exc

from app_lstm_next.models.app_lstm_next import AppLSTMNext
from app_lstm_next.train.train_app_lstm_next import (
    DEFAULT_APP_DATASET_DIR,
    DEFAULT_CHECKPOINT_DIR,
    DEFAULT_DATASET_DIR,
    DEFAULT_RESULTS_PATH,
    PAD_TOKEN,
    evaluate,
    filter_rows_by_target,
    load_csv,
    make_loader,
    result_rows_for_metrics,
    validate_vocabs,
    write_results,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate WhatsNextApp bidirectional LSTM checkpoint.")
    parser.add_argument(
        "--checkpoint",
        default=str(DEFAULT_CHECKPOINT_DIR / "app_lstm_next_bidirectional_best_val_recall8.pt"),
    )
    parser.add_argument("--dataset-dir", default=str(DEFAULT_APP_DATASET_DIR if DEFAULT_APP_DATASET_DIR.exists() else DEFAULT_DATASET_DIR))
    parser.add_argument("--output", default=str(DEFAULT_RESULTS_PATH.with_name("eval_results.csv")))
    parser.add_argument("--split", nargs="+", choices=["val", "test"], default=["val", "test"])
    parser.add_argument("--top-k", nargs="+", type=int, default=[1, 2, 3, 4, 5, 6, 7, 8])
    parser.add_argument("--checkpoint-type", default="best_val_recall8")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)

    payload = torch.load(args.checkpoint, map_location=device)
    input_app_vocab = payload["input_app_vocab"]
    target_app_vocab = payload["target_app_vocab"]
    validate_vocabs(input_app_vocab, target_app_vocab)

    model = AppLSTMNext(
        num_input_tokens=payload["num_input_tokens"],
        num_target_apps=payload["num_target_apps"],
        pad_id=payload["pad_id"],
        embedding_dim=payload["embedding_dim"],
        hidden_dim=payload["hidden_dim"],
        dropout=payload["dropout"],
    ).to(device)
    model.load_state_dict(payload["model_state_dict"])
    criterion = nn.CrossEntropyLoss()

    dataset_dir = Path(args.dataset_dir)
    rows_out = []
    metric_args = argparse.Namespace(
        top_k=args.top_k,
        history_len=payload["history_len"],
        window_seconds=payload["window_seconds"],
        embedding_dim=payload["embedding_dim"],
        hidden_dim=payload["hidden_dim"],
        dropout=payload["dropout"],
        batch_size=payload["batch_size"],
        epochs=payload["epochs"],
        lr=payload["learning_rate"],
        seed=payload["seed"],
    )
    for split in args.split:
        raw_rows = load_csv(dataset_dir / f"{split}.csv")
        rows, excluded = filter_rows_by_target(raw_rows, target_app_vocab, split)
        loader = make_loader(
            rows,
            input_app_vocab,
            target_app_vocab,
            payload["history_len"],
            payload["batch_size"],
            shuffle=False,
        )
        metrics = evaluate(model, loader, criterion, args.top_k, device)
        rows_out.extend(
            result_rows_for_metrics(
                split,
                args.checkpoint_type,
                metrics,
                metric_args,
                input_app_vocab,
                target_app_vocab,
                excluded,
            )
        )
        print(
            f"{split} Recall@1={metrics['recall_at'].get(1, 0.0):.6f} "
            f"Recall@5={metrics['recall_at'].get(5, 0.0):.6f} "
            f"Recall@8={metrics['recall_at'].get(8, 0.0):.6f} "
            f"n={metrics['num_samples']}"
        )

    write_results(Path(args.output), rows_out)
    print(f"results saved: {args.output}")


if __name__ == "__main__":
    main()
