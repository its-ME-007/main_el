# Shared runner for run_tt_hebbal.ps1 / run_tt_baiyappanahalli.ps1 (dot-sourced; not run on its own).
# Re-validation on TomTom free-flow speeds (the <area>_tt aliases, HANDOVER.md), unattended and resumable:
#  - each finished step is recorded in data\overnight\tt_<area>_done.txt and skipped on a rerun;
#  - progress (START / END / SKIP / INTERRUPTED, exit code, minutes) goes to data\overnight\tt_<area>_progress.txt;
#  - a failed step stops the script with "INTERRUPTED at <step>"; rerun the same script to resume there
#    (evaluate / noise / combos also keep per-scenario checkpoints, so finished simulations are not redone);
#  - a lock (data\overnight\tt.lock) makes a second script WAIT until the first is done: never two sims at once;
#  - the PC is kept awake while a script runs (no setting is changed).
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$Log = "data\overnight"
New-Item -ItemType Directory -Force $Log | Out-Null

Add-Type -Namespace Tt -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[Tt.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

function Note($area, $text) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm') $text"
    Write-Host $line
    Add-Content -Encoding utf8 "$Log\tt_${area}_progress.txt" $line
}

function Lock-Sims($area) {
    $lock = "$Log\tt.lock"
    while (Test-Path $lock) {
        $owner = Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $owner -or -not (Get-Process -Id ([int]$owner) -ErrorAction SilentlyContinue)) { break }   # stale
        Note $area "WAIT another tt script (pid $owner) is running; checking again in 60 s"
        Start-Sleep 60
    }
    Set-Content $lock $PID
}

function Unlock-Sims { Remove-Item "$Log\tt.lock" -ErrorAction SilentlyContinue }

function Start-Run($area) {
    Lock-Sims $area
    $prog = "$Log\tt_${area}_progress.txt"
    if (Test-Path $prog) {
        $last = Get-Content $prog | Where-Object { $_ -match ' (START|END|INTERRUPTED) ' } | Select-Object -Last 1
        if ($last -match ' START (\S+)') { Note $area "RESUME previous run stopped during $($Matches[1]) (killed / power loss)" }
        elseif ($last -match 'INTERRUPTED at (\S+)') { Note $area "RESUME previous run failed at $($Matches[1])" }
    }
    Note $area "RUN $area (pid $PID)"
}

function Test-Done($area, $name) {
    $done = "$Log\tt_${area}_done.txt"
    (Test-Path $done) -and ((Get-Content $done) -contains $name)
}

function Step($area, $name, $cmd) {
    if (Test-Done $area $name) { Note $area "SKIP  $name (done earlier)"; return }
    $t = Get-Date
    Note $area "START $name :: $cmd"
    cmd /c "$cmd > $Log\tt_${area}_$name.log 2>&1"
    $code = $LASTEXITCODE
    $min = [math]::Round(((Get-Date) - $t).TotalMinutes)
    if ($code -ne 0) {
        Note $area "INTERRUPTED at $name (exit $code, $min min) -- see $Log\tt_${area}_$name.log; rerun this script to resume"
        Unlock-Sims
        exit 1
    }
    Add-Content "$Log\tt_${area}_done.txt" $name
    Note $area "END   $name exit=0 ($min min)"
}

function Pick($area, $what) {
    $v = (cmd /c "uv run python -m urban.pick $area $what 2>nul") | Select-Object -Last 1
    if (-not $v) { Note $area "INTERRUPTED at pick $what (no result)"; Unlock-Sims; exit 1 }
    $v.Trim()
}

function Finish-Run($area) {
    Note $area "ALL DONE $area"
    Unlock-Sims
    [Tt.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
}
