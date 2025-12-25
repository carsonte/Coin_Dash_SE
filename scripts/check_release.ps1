$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

Write-Host "[check] pytest"
python -m pytest --disable-warnings

if ($env:RUN_LLM_SMOKE -eq "1") {
    if (Test-Path ".env") {
        Write-Host "[check] llm smoke"
        python -m dotenv run -- python scripts/smoke_llm_clients.py
    } else {
        Write-Host "[skip] .env missing; llm smoke skipped"
    }
}

if ($env:RUN_BACKTEST -eq "1") {
    Write-Host "[check] backtest sample"
    $sample = "data/sample/BTCUSDT_30m.sample.csv"
    if (Test-Path $sample) {
        $prevWebhook = $env:LARK_WEBHOOK
        $env:LARK_WEBHOOK = ""
        if ($env:RUN_DEEPSEEK -eq "1") {
            python -m coin_dash.cli backtest --symbol BTCUSDm --csv $sample --deepseek
        } else {
            python -m coin_dash.cli backtest --symbol BTCUSDm --csv $sample
        }
        if ($null -ne $prevWebhook) {
            $env:LARK_WEBHOOK = $prevWebhook
        } else {
            Remove-Item Env:\LARK_WEBHOOK -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "[skip] sample CSV missing: $sample"
    }
}

Write-Host "[ok] done"
