# Baiyappanahalli full evaluation (2026-11-27): micro check of the macro top 10 over 5 seeds, then sets of roads.
# Same stable demand as the basic run (FLYOVER_RATE 1830 + OTHER_RATE 1970 = 3,800 through, split evenly);
# finished runs from run_overnight.ps1 are reused through their checkpoints.
# Run: cd D:\7_main_el\backend; powershell -ExecutionPolicy Bypass -File .\run_bai_full.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$log = "data\overnight"
New-Item -ItemType Directory -Force $log | Out-Null

function Step($name, $cmd) {
    $t = Get-Date
    "$(Get-Date -Format 'HH:mm') START $name" | Tee-Object -Append "$log\bai_full_progress.txt"
    cmd /c "$cmd > $log\$name.log 2>&1"
    $min = [math]::Round(((Get-Date) - $t).TotalMinutes)
    "$(Get-Date -Format 'HH:mm') END   $name  exit=$LASTEXITCODE  ($min min)" | Tee-Object -Append "$log\bai_full_progress.txt"
}

$env:FLYOVER_RATE = "1830"; $env:OTHER_RATE = "1970"
Step "b1_bai_noise_top10" "uv run python -u -m urban.noise baiyappanahalli --cands 21,22,19,15,18,20,23,24,6,13 --seeds 42,1,2,3,4 --workers 2"
Step "b2_bai_export" "uv run python -u -m urban.export baiyappanahalli"
Step "b3_bai_combos" "uv run python -u -m urban.combos baiyappanahalli --pool 10 --max 4 --workers 4 --micro-seeds 5"
Step "b4_bai_export" "uv run python -u -m urban.export baiyappanahalli"
Remove-Item Env:FLYOVER_RATE, Env:OTHER_RATE -ErrorAction SilentlyContinue
"$(Get-Date -Format 'HH:mm') ALL DONE" | Tee-Object -Append "$log\bai_full_progress.txt"
