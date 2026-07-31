"""WhatsNextApp paper-best bidirectional LSTM for next-app prediction."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence


class AppLSTMNext(nn.Module):
    """Embedding -> bidirectional LSTM -> Dense logits."""

    def __init__(
        self,
        num_input_tokens: int,
        num_target_apps: int,
        pad_id: int,
        embedding_dim: int = 64,
        hidden_dim: int = 64,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.num_input_tokens = int(num_input_tokens)
        self.num_target_apps = int(num_target_apps)
        self.pad_id = int(pad_id)
        self.embedding_dim = int(embedding_dim)
        self.hidden_dim = int(hidden_dim)

        self.embedding = nn.Embedding(
            self.num_input_tokens,
            self.embedding_dim,
            padding_idx=self.pad_id,
        )
        self.lstm = nn.LSTM(
            input_size=self.embedding_dim,
            hidden_size=self.hidden_dim,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.dropout = nn.Dropout(dropout)
        self.output = nn.Linear(self.hidden_dim * 2, self.num_target_apps)

    def forward(self, history_apps: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """Return raw next-app logits for padded input shape (batch, sequence_len)."""
        embedded = self.embedding(history_apps)
        packed = pack_padded_sequence(
            embedded,
            lengths.cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, (hidden, _) = self.lstm(packed)
        forward_hidden = hidden[-2]
        backward_hidden = hidden[-1]
        representation = torch.cat([forward_hidden, backward_hidden], dim=1)
        return self.output(self.dropout(representation))
