# Hebbal on TomTom free-flow speeds (area alias hebbal_tt), every step, unattended, resumable. ~2-2.5 h.
# Run in a plain PowerShell window:  cd D:\7_main_el\backend; powershell -ExecutionPolicy Bypass -File .\run_tt_hebbal.ps1
# Progress: data\overnight\tt_hebbal_tt_progress.txt ; rerun the same command to resume after any stop.
. "$PSScriptRoot\run_tt_common.ps1"
$A = "hebbal_tt"
Remove-Item Env:FLYOVER_RATE, Env:OTHER_RATE, Env:SPEEDS, Env:DURATION -ErrorAction SilentlyContinue   # defaults only
Start-Run $A

Step $A "1_data"       "uv run python -u -m urban.data $A"
Step $A "2_baseline"   "uv run python -u -m urban.sim $A"
Step $A "3_validate"   "uv run python -u -m urban.validate $A"
Step $A "4_candidates" "uv run python -u -m urban.candidates $A"
Step $A "5_macro"      "uv run python -u -m urban.evaluate $A --workers 4"
if (-not (Test-Done $A "6_micro")) { $top = Pick $A "top10"; Note $A "top 10 (macro): $top" }
Step $A "6_micro"      "uv run python -u -m urban.noise $A --cands $top --seeds 42,1,2,3,4 --workers 2"
Step $A "7_combos"     "uv run python -u -m urban.combos $A --pool 10 --max 4 --workers 4 --micro-seeds 5"
if (-not (Test-Done $A "8_animation")) { $win = Pick $A "winner"; Note $A "winner (micro): c$win" }
Step $A "8_animation"  "uv run python -u -m urban.fcd $A --cands $win"
Step $A "9_export"     "uv run python -u -m urban.export $A"
Finish-Run $A
