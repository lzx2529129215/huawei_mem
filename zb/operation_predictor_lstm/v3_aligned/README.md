# v3_aligned

`v3_aligned` is a minimal V3-derived next-app experiment aligned to the
`app_lstm_next` paper-input dataset.

It directly reads:

- `app_lstm_next/data/processed/app_lstm_next/train.csv`
- `app_lstm_next/data/processed/app_lstm_next/val.csv`
- `app_lstm_next/data/processed/app_lstm_next/test.csv`
- `app_lstm_next/data/processed/app_lstm_next/dataset_meta.json`
- `app_lstm_next/data/vocab/input_app_vocab.json`
- `app_lstm_next/data/vocab/target_app_vocab.json`

The only model input is `history_apps`; the label is `target_app`.
`user_id` and `target_timestamp` are kept for validation and traceability but
are not fed into the model.

Compared with original `v3`, this version removes duration features,
`opened_apps`, time features, user groups, horizon heads, and checkpoint
compatibility loading. It keeps the V3 single-direction LSTM shape:

`Embedding -> LSTM -> shared Linear/ReLU/Dropout -> next_app_head`

Train:

```bash
cd lzx/operation_predictor
python -m v3_aligned.scripts.train_next_app
```

Train with per-sample inference input/output trace:

```bash
cd lzx/operation_predictor
python -m v3_aligned.scripts.train_next_app \
  --inference-trace-output outputs/results/v3_aligned/inference_trace.csv \
  --inference-trace-splits train val test \
  --inference-trace-top-k 8
```

Add `--trace-validation-each-epoch` to also write validation-set inference
rows after every epoch.

Default outputs:

- `outputs/checkpoints/v3_aligned/v3_aligned_last.pt`
- `outputs/checkpoints/v3_aligned/v3_aligned_best_val_recall8.pt`
- `outputs/results/v3_aligned/results.csv`
- `outputs/results/v3_aligned/inference_trace.csv` when trace output is enabled
