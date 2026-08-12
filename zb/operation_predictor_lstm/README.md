# zb/operation_predictor_lstm

这是从 `lzx/operation_predictor` 精简出来的下一应用预测实验目录，只保留
`app_lstm_next` 和 `v3_aligned` 两个模型及其直接相关的数据、词表、脚本和输出产物。

详细模型说明见 [docs/模型说明.md](docs/模型说明.md)。

## 包含内容

- `app_lstm_next/`：双向 LSTM 下一应用预测模型，含训练、评估、推理、测试、模型代码、处理后数据、词表和日志。
- `v3_aligned/`：与 `app_lstm_next` 输入对齐的 V3 风格单向 LSTM 模型，含训练入口和模型代码。
- `v3/src/data/build_v3_next_app_aligned_dataset.py`：生成 V3 对齐数据集的脚本。
- `data/vocab/`：共享应用词表、用户群体词表，以及原始 Excel `大学生-100-interaction-jank.xlsx`。
- `data/raw/lsapp/`：由 Excel 生成的 `app_events.csv`、检查文件和生成脚本。
- `data/processed/app_lstm_next/`：根级备份的 `app_lstm_next` 数据切分。
- `data/processed/v3_next_app_aligned/`：V3 对齐数据切分和对齐报告。
- `outputs/checkpoints/app_lstm_next/`、`outputs/checkpoints/v3_aligned/`：两个模型的 checkpoint。
- `outputs/results/app_lstm_next/`、`outputs/results/v3_aligned/`：两个模型的结果 CSV 和推理 trace。
- `scripts/tools/data/lsapp/`、`scripts/tools/prepare_lsapp_app_events.py`：从 LSApp/映射数据准备 `app_events` 的相关辅助脚本。
- `src/utils/io_utils.py`：数据准备脚本依赖的轻量 I/O 工具。

## 不包含内容

- v1/v2 baseline
- operation-level 模型
- duration/forecast 模型
- paper/full-v3 变体
- Python 缓存和无关结果目录
