# Registers two weekday tasks for the intraday ORB bot on THIS laptop.
#   ORB-PreMarket   09:05 IST  -> brain.py --mode pre_market
#   ORB-MarketOpen  09:31 IST  -> brain.py --mode market_open
# Run once:   powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
# Remove:     Unregister-ScheduledTask -TaskName ORB-PreMarket,ORB-MarketOpen -Confirm:$false

$dir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat  = Join-Path $dir "run_intraday.bat"
$days = 'Monday','Tuesday','Wednesday','Thursday','Friday'

# WakeToRun: wake the laptop from sleep. No StartWhenAvailable on purpose:
# a missed 09:31 run must NOT fire hours later with stale signals.
$settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

$jobs = @(
  @{ Name = 'ORB-PreMarket';  At = '9:05AM'; Mode = 'pre_market'  },
  @{ Name = 'ORB-MarketOpen'; At = '9:31AM'; Mode = 'market_open' }
)

foreach ($j in $jobs) {
  $action  = New-ScheduledTaskAction -Execute $bat -Argument $j.Mode -WorkingDirectory $dir
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $j.At
  Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger `
      -Settings $settings -Description "Intraday ORB $($j.Mode)" -Force | Out-Null
  Write-Host "Registered $($j.Name) at $($j.At) Mon-Fri"
}

Get-ScheduledTask -TaskName ORB-PreMarket,ORB-MarketOpen |
  Select-Object TaskName, State, @{n='NextRun';e={(Get-ScheduledTaskInfo $_).NextRunTime}}
