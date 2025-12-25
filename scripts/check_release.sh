#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[check] pytest"
python -m pytest --disable-warnings

if [[ "${RUN_LLM_SMOKE:-}" == "1" ]]; then
  if [[ -f ".env" ]]; then
    echo "[check] llm smoke"
    python -m dotenv run -- python scripts/smoke_llm_clients.py
  else
    echo "[skip] .env missing; llm smoke skipped"
  fi
fi

if [[ "${RUN_BACKTEST:-}" == "1" ]]; then
  echo "[check] backtest sample"
  sample="data/sample/BTCUSDT_30m.sample.csv"
  if [[ -f "$sample" ]]; then
    if [[ "${RUN_DEEPSEEK:-}" == "1" ]]; then
      LARK_WEBHOOK="" python -m coin_dash.cli backtest --symbol BTCUSDm --csv "$sample" --deepseek
    else
      LARK_WEBHOOK="" python -m coin_dash.cli backtest --symbol BTCUSDm --csv "$sample"
    fi
  else
    echo "[skip] sample CSV missing: $sample"
  fi
fi

echo "[ok] done"
