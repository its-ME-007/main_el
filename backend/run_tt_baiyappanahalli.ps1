# Baiyappanahalli on TomTom free-flow speeds (area alias baiyappanahalli_tt), every step, unattended, resumable.
# ~5-7 h (the 5-seed micro check is the long part). Run in a plain PowerShell window:
#   cd D:\7_main_el\backend; powershell -ExecutionPolicy Bypass -File .\run_tt_baiyappanahalli.ps1
# Progress: data\overnight\tt_baiyappanahalli_tt_progress.txt ; rerun the same command to resume after any stop.
# Started together with run_tt_hebbal.ps1, it waits for that one to finish (lock), so sims never overlap.
. "$PSScriptRoot\run_tt_common.ps1"
$A = "baiyappanahalli_tt"
Remove-Item Env:SPEEDS, Env:DURATION -ErrorAction SilentlyContinue
Start-Run $A

# Demand: the stable uncalibrated level of the basic run (3,800 through, split evenly). Slower roads can tip this
# network into gridlock, so after the baseline the demand is cut by 20 % (at most twice) until the baseline is
# healthy (<= 100 teleports, <= 600 s time loss); the level used is kept in tt_baiyappanahalli_tt_rates.txt so
# a resumed run uses the same demand for every step.
$ratesFile = "$Log\tt_${A}_rates.txt"
if (Test-Path $ratesFile) { $fly, $oth = (Get-Content $ratesFile | Select-Object -First 1).Split(",") }
else { $fly, $oth = 1830, 1970 }
$env:FLYOVER_RATE = "$fly"; $env:OTHER_RATE = "$oth"

Step $A "1_data" "uv run python -u -m urban.data $A"
if (-not (Test-Done $A "2_baseline")) {
    foreach ($try in 1..3) {
        Note $A "baseline try $try at FLYOVER_RATE=$fly OTHER_RATE=$oth"
        Step $A "2_baseline_try$try" "uv run python -u -m urban.sim $A"
        if ((Pick $A "healthy") -eq "1") { break }
        if ($try -eq 3) { Note $A "INTERRUPTED at 2_baseline: still gridlocked after 2 cuts; lower the rates by hand"; Unlock-Sims; exit 1 }
        $fly = [int]($fly * 0.8); $oth = [int]($oth * 0.8)
        $env:FLYOVER_RATE = "$fly"; $env:OTHER_RATE = "$oth"
        Note $A "gridlocked: demand cut 20 %"
    }
    Set-Content $ratesFile "$fly,$oth"
    Add-Content "$Log\tt_${A}_done.txt" "2_baseline"
    Note $A "END   2_baseline at FLYOVER_RATE=$fly OTHER_RATE=$oth"
}
Step $A "3_validate"   "uv run python -u -m urban.validate $A"
Step $A "4_candidates" "uv run python -u -m urban.candidates $A"
Step $A "5_macro"      "uv run python -u -m urban.evaluate $A --workers 4"
if (-not (Test-Done $A "6_micro")) { $top = Pick $A "top10"; Note $A "top 10 (macro): $top" }
Step $A "6_micro"      "uv run python -u -m urban.noise $A --cands $top --seeds 42,1,2,3,4 --workers 2"
Step $A "7_combos"     "uv run python -u -m urban.combos $A --pool 10 --max 4 --workers 4 --micro-seeds 5"
if (-not (Test-Done $A "8_animation")) { $win = Pick $A "winner"; Note $A "winner (micro): c$win" }
Step $A "8_animation"  "uv run python -u -m urban.fcd $A --cands $win"
Step $A "9_export"     "uv run python -u -m urban.export $A"
Remove-Item Env:FLYOVER_RATE, Env:OTHER_RATE -ErrorAction SilentlyContinue
Finish-Run $A
