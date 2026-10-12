# Registers a logon task that runs the monitor in the background (pythonw, no console window).
$ErrorActionPreference = "Stop"
$TaskName = "Ditoo Claude Usage"
$Root = $PSScriptRoot

if (-not (Test-Path "$Root\config.json")) {
    throw "config.json not found. Copy config.example.json to config.json and edit it first."
}

$Pythonw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
if (-not (Test-Path $Pythonw)) { throw "pythonw.exe not found next to python.exe" }

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "`"$Root\ditoo_usage.py`"" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started '$TaskName'. Log: $env:USERPROFILE\.ditoo\monitor.log"
