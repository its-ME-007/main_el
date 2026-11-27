# Overnight batch (2026-11-27): everything before the presentation, one simulation at a time.
# Run from a plain PowerShell window:  cd D:\7_main_el\backend; .\run_overnight.ps1
# Logs: data\overnight\*.log (plain text). A failed step is logged and the next one still runs.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$log = "data\overnight"
New-Item -ItemType Directory -Force $log | Out-Null

function Step($name, $cmd) {
    $t = Get-Date
    "$(Get-Date -Format 'HH:mm') START $name" | Tee-Object -Append "$log\progress.txt"
    cmd /c "$cmd > $log\$name.log 2>&1"
    $min = [math]::Round(((Get-Date) - $t).TotalMinutes)
    "$(Get-Date -Format 'HH:mm') END   $name  exit=$LASTEXITCODE  ($min min)" | Tee-Object -Append "$log\progress.txt"
}

# --- 1. Hebbal: micro 5-seed check of the macro top 10 (core result) -------------------------------------------
Remove-Item Env:FLYOVER_RATE, Env:OTHER_RATE -ErrorAction SilentlyContinue
Step "1_hebbal_noise" "uv run python -u -m urban.noise hebbal --cands 11,7,21,5,20,4,14,15,16,9 --workers 2"
Step "2_hebbal_export" "uv run python -u -m urban.export hebbal"

# --- 2. Baiyappanahalli basic: the demand level that ran stably (3,800 through split evenly, ~47 veh/h per pair) --
# Both variables must stay set for every Baiyappanahalli step: evaluate/noise regenerate the demand from them.
$env:FLYOVER_RATE = "1830"; $env:OTHER_RATE = "1970"
Step "3_bai_baseline" "uv run python -u -m urban.sim baiyappanahalli"
Step "4_bai_candidates" "uv run python -u -m urban.candidates baiyappanahalli"
Step "5_bai_macro" "uv run python -u -m urban.evaluate baiyappanahalli --workers 4"
$top3 = (uv run python -c "import pandas as pd; print(','.join(str(int(c)) for c in pd.read_csv('data/baiyappanahalli/scenarios_macro.csv').sort_values('score', ascending=False).cand.head(3)))") | Select-Object -Last 1
"top 3 Baiyappanahalli: $top3" | Tee-Object -Append "$log\progress.txt"
Step "6_bai_noise" "uv run python -u -m urban.noise baiyappanahalli --cands $top3 --seeds 42,1,2 --workers 2"
Step "7_bai_export" "uv run python -u -m urban.export baiyappanahalli"
Remove-Item Env:FLYOVER_RATE, Env:OTHER_RATE -ErrorAction SilentlyContinue

# --- 3. Hebbal combinations (extra; last so the core results are safe if it is slow) -----------------------------
Step "8_hebbal_combos" "uv run python -u -m urban.combos hebbal --pool 10 --max 4 --workers 4 --micro-seeds 3"
Step "9_hebbal_export" "uv run python -u -m urban.export hebbal"
"$(Get-Date -Format 'HH:mm') ALL DONE" | Tee-Object -Append "$log\progress.txt"
