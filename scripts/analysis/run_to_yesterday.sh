#!/usr/bin/env zsh
set -euo pipefail

today=$(date +%F)
for f in gold_*.csv; do
  d=${f#gold_}
  d=${d%.csv}
  [[ "$d" < "$today" ]] || continue
  ~/venv/bin/python generate_daily_kline.py "$f"
done
