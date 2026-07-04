cd /home/lzx/Desktop/huawei/huawei_mem/lzx/runtime_monitor

mkdir -p output/session_files_001

python3 monitor.py \
  --config config.yaml \
  --target-app WPS \
  --sample-interval 1 \
  --output-dir ./output/session_files_001 \
  --path-mode hash