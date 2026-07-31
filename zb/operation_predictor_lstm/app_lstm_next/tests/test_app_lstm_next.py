from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_lstm_next.models.app_lstm_next import AppLSTMNext
from app_lstm_next.train.train_app_lstm_next import (
    PAD_TOKEN,
    UNKNOWN_TOKEN,
    AppNextDataset,
    collate_fn,
    evaluate,
    filter_rows_by_target,
    set_seed,
)


class FixedRankModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.num_target_apps = 5

    def forward(self, history_apps: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        batch_size = history_apps.shape[0]
        logits = torch.tensor([[1.0, 2.0, 4.0, 0.0, 5.0]], device=history_apps.device)
        return logits.repeat(batch_size, 1)


class AppLSTMNextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.input_vocab = {PAD_TOKEN: 0, UNKNOWN_TOKEN: 1}
        for idx in range(40):
            self.input_vocab[f"app{idx}"] = len(self.input_vocab)
        self.target_vocab = {f"target{idx}": idx for idx in range(5)}

    def test_dataset_truncates_pads_and_tracks_lengths(self) -> None:
        long_history = "|".join(f"app{idx}" for idx in range(30))
        rows = [
            {"history_apps": long_history, "target_app": "target2"},
            {"history_apps": "app1|app2", "target_app": "target1"},
        ]
        dataset = AppNextDataset(rows, self.input_vocab, self.target_vocab, history_len=23)

        first = dataset[0]
        self.assertEqual(int(first["lengths"].item()), 23)
        self.assertEqual(first["history_apps"][0].item(), self.input_vocab["app7"])
        self.assertEqual(first["history_apps"][-1].item(), self.input_vocab["app29"])

        batch = collate_fn([dataset[0], dataset[1]])
        self.assertEqual(tuple(batch["history_apps"].shape), (2, 23))
        self.assertEqual(batch["lengths"].tolist(), [23, 2])
        self.assertTrue(torch.equal(batch["history_apps"][1, 2:], torch.zeros(21, dtype=torch.long)))

    def test_bidirectional_lstm_shapes_and_training_step(self) -> None:
        set_seed(123)
        rows = [
            {"history_apps": "app1|app2|app3", "target_app": "target2"},
            {"history_apps": "app4", "target_app": "target1"},
        ]
        dataset = AppNextDataset(rows, self.input_vocab, self.target_vocab, history_len=23)
        batch = collate_fn([dataset[0], dataset[1]])
        model = AppLSTMNext(
            num_input_tokens=len(self.input_vocab),
            num_target_apps=len(self.target_vocab),
            pad_id=self.input_vocab[PAD_TOKEN],
        )

        embedded = model.embedding(batch["history_apps"])
        packed = pack_padded_sequence(embedded, batch["lengths"].cpu(), batch_first=True, enforce_sorted=False)
        _, (hidden, _) = model.lstm(packed)
        self.assertEqual(tuple(hidden.shape), (2, 2, 64))
        representation = torch.cat([hidden[-2], hidden[-1]], dim=1)
        self.assertEqual(tuple(representation.shape), (2, 128))

        logits = model(batch["history_apps"], batch["lengths"])
        self.assertEqual(tuple(logits.shape), (2, len(self.target_vocab)))
        self.assertNotIn(PAD_TOKEN, self.target_vocab)
        self.assertNotIn(UNKNOWN_TOKEN, self.target_vocab)

        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss = nn.CrossEntropyLoss()(logits, batch["target_app"])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

    def test_unknown_val_test_targets_are_filtered(self) -> None:
        rows = [
            {"history_apps": "app1", "target_app": "target1"},
            {"history_apps": "app1", "target_app": "new_target"},
            {"history_apps": "app1", "target_app": UNKNOWN_TOKEN},
        ]
        kept, excluded = filter_rows_by_target(rows, self.target_vocab, "val")
        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, 2)

    def test_recall_at_k_uses_raw_logits(self) -> None:
        rows = [{"history_apps": "app1|app2", "target_app": "target2"}]
        dataset = AppNextDataset(rows, self.input_vocab, self.target_vocab, history_len=23)
        loader = torch.utils.data.DataLoader(dataset, batch_size=1, collate_fn=collate_fn)
        metrics = evaluate(FixedRankModel(), loader, nn.CrossEntropyLoss(), [1, 2, 3, 4], torch.device("cpu"))
        self.assertEqual(metrics["recall_at"][1], 0.0)
        self.assertEqual(metrics["recall_at"][2], 1.0)
        self.assertEqual(metrics["recall_at"][3], 1.0)
        self.assertEqual(metrics["recall_at"][4], 1.0)

    def test_seed_and_checkpoint_reload_are_reproducible(self) -> None:
        rows = [{"history_apps": "app1|app2|app3", "target_app": "target2"}]
        dataset = AppNextDataset(rows, self.input_vocab, self.target_vocab, history_len=23)
        batch = collate_fn([dataset[0]])

        set_seed(7)
        model = AppLSTMNext(
            num_input_tokens=len(self.input_vocab),
            num_target_apps=len(self.target_vocab),
            pad_id=self.input_vocab[PAD_TOKEN],
        )
        model.eval()
        before = model(batch["history_apps"], batch["lengths"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.pt"
            torch.save({"model_state_dict": model.state_dict()}, path)
            reloaded = AppLSTMNext(
                num_input_tokens=len(self.input_vocab),
                num_target_apps=len(self.target_vocab),
                pad_id=self.input_vocab[PAD_TOKEN],
            )
            reloaded.load_state_dict(torch.load(path, map_location="cpu")["model_state_dict"])
            reloaded.eval()
            after = reloaded(batch["history_apps"], batch["lengths"])

        self.assertTrue(torch.allclose(before, after))


if __name__ == "__main__":
    unittest.main()
