"""V3-style single-direction LSTM aligned to app_lstm_next inputs."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence


class AppLSTMAlignedV3(nn.Module):
    """App sequence encoder using only history_apps for next-app classification."""

    def __init__(
        self,
        num_apps: int,
        num_target_apps: int,
        pad_id: int,
        app_embedding_dim: int = 32,
        hidden_dim: int = 64,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.num_apps = int(num_apps)
        self.num_target_apps = int(num_target_apps)
        self.pad_id = int(pad_id)
        self.app_embedding = nn.Embedding(
            self.num_apps,
            app_embedding_dim,
            padding_idx=self.pad_id,
        )
        self.lstm = nn.LSTM(
            input_size=app_embedding_dim,
            hidden_size=hidden_dim,
            batch_first=True,
        )
        self.shared = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.next_app_head = nn.Linear(hidden_dim, self.num_target_apps)

    def forward(self, history_apps: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        app_emb = self.app_embedding(history_apps)
        packed = pack_padded_sequence(
            app_emb,
            lengths.cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, (hidden, _) = self.lstm(packed)
        shared_features = self.shared(hidden[-1])
        return self.next_app_head(shared_features)
