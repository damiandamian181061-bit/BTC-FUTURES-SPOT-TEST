# Installs the five Windows Task Scheduler tasks that run the paper-trading bot through WSL
# (four harness commands + the 23:10 UTC dashboard, which only reads the logs and rewrites data/paper/dashboard.html).
# Run ONCE in PowerShell (not as administrator; plain PowerShell is fine):
#   powershell -ExecutionPolicy Bypass -File "C:\Users\damia\Documents\BTC Strategy Project\scheduler\install_tasks.ps1"
# Safe to re-run: existing tasks are replaced. Remove them with uninstall_tasks.ps1.
#
# Times are UTC (the trailing Z in StartBoundary = "synchronize across time zones"), so the BST change does not shift them.
# a-enter / a-exit start 30 s early: WSL takes a few seconds to boot and harness.py waits for the exact second itself.
# "WakeToRun" wakes the laptop from sleep. It cannot turn on a laptop that is shut down, and Windows may not wake
# from sleep with the lid closed on every model: keep it plugged in and check data/paper/logs/*.log for a few days.
#
# Registration goes through schtasks.exe /XML (clearer errors than Register-ScheduledTask -Xml).
# Task names must not contain ':' (a task is stored as a file under %SystemRoot%\System32\Tasks, so file-name rules
# apply): "BTC bot - b-check 00:01 UTC" failed with "The parameter is incorrect" on 16 Nov 2026; dots are used instead.

$proj = "C:\Users\damia\Documents\BTC Strategy Project"
$wslProj = "/mnt/c/Users/damia/Documents/BTC Strategy Project"
$wsl = (Get-Command wsl.exe).Source
$user = "$env:USERDOMAIN\$env:USERNAME"
$tomorrow = (Get-Date).ToUniversalTime().AddDays(1).ToString("yyyy-MM-dd")

$tasks = @(
  @{ Name = "BTC bot - b-check 00.01 UTC";   Cmd = "b-check";    Time = "00:01:00" },
  @{ Name = "BTC bot - a-precheck 20.55 UTC"; Cmd = "a-precheck"; Time = "20:55:00" },
  @{ Name = "BTC bot - a-enter 21.00 UTC";   Cmd = "a-enter";    Time = "20:59:30" },
  @{ Name = "BTC bot - a-exit 22.55 UTC";    Cmd = "a-exit";     Time = "22:54:30" },
  @{ Name = "BTC bot - dashboard 23.10 UTC"; Cmd = "dashboard";  Time = "23:10:00" }
)

$failed = 0
foreach ($t in $tasks) {
  $args = "-e bash `"$wslProj/scripts/run.sh`" $($t.Cmd)"
  $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>BTC paper-trading bot: run.sh $($t.Cmd) (STRATEGY_RULES.md v1.1). Logs: $proj\data\paper\logs</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>${tomorrow}T$($t.Time)Z</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$user</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>$wsl</Command><Arguments>$args</Arguments></Exec>
  </Actions>
</Task>
"@
  $tmp = Join-Path $env:TEMP ("btc-bot-" + $t.Cmd + ".xml")
  [IO.File]::WriteAllText($tmp, $xml, [Text.Encoding]::Unicode)
  $out = & schtasks.exe /Create /F /TN $t.Name /XML $tmp 2>&1
  Remove-Item $tmp -ErrorAction SilentlyContinue
  if ($LASTEXITCODE -eq 0) {
    Write-Host ("installed: {0}  ->  wsl.exe {1}" -f $t.Name, $args)
  } else {
    $failed++
    Write-Host ("FAILED:    {0}  ->  {1}" -f $t.Name, ($out -join " "))
  }
}
Write-Host ""
Write-Host "Next run times (shown in your LOCAL time):"
Get-ScheduledTask -TaskName "BTC bot - *" | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime | Format-Table -AutoSize
Write-Host "Test one now without waiting:  Start-ScheduledTask -TaskName 'BTC bot - dashboard 23.10 UTC'   (harmless: it only reads the logs; then open data\paper\dashboard.html)"
Write-Host "Or:                             Start-ScheduledTask -TaskName 'BTC bot - a-exit 22.55 UTC'      (A is flat, so it just logs 'nothing to exit')"
if ($failed) { Write-Host "$failed task(s) FAILED to register: see above."; exit 1 }
