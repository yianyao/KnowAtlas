# Install/uninstall a Windows scheduled task running context_watcher.py --once every N minutes.
# Usage:
#   powershell -NoProfile -File tools/install_watcher_task.ps1
#   powershell -NoProfile -File tools/install_watcher_task.ps1 -Minutes 2
#   powershell -NoProfile -File tools/install_watcher_task.ps1 -StartNow
#   powershell -NoProfile -File tools/install_watcher_task.ps1 -Uninstall
# NOTE: ASCII only. Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI.
param(
    [int]$Minutes = 2,
    [switch]$StartNow,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$taskName = 'KnowAtlasContextWatcher'
$root = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    "Uninstalled scheduled task $taskName"
    return
}

if ($Minutes -lt 1) { throw '-Minutes must be >= 1' }
$uv = (Get-Command uv -ErrorAction Stop).Source
$script = Join-Path $root 'tools\context_watcher.py'
$launcher = Join-Path $root 'tools\run_hidden.vbs'
# Run through wscript + run_hidden.vbs: a console app started by Task Scheduler in an
# interactive session pops a visible window every run. WScript.Shell.Run with style 0
# hides it (no flash), and still reports the child exit code to the task.
$arguments = "//nologo `"$launcher`" `"$uv`" `"$root`""

try {
    $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $Minutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew -Hidden
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description 'KnowAtlas context threshold / handoff watcher (WeChat + desktop notify)' -Force | Out-Null
    "Installed scheduled task: $taskName (every $Minutes min)"
} catch {
    Write-Warning "ScheduledTasks registration failed, falling back to schtasks: $($_.Exception.Message)"
    $tr = "wscript.exe //nologo `"$launcher`" `"$uv`" `"$root`""
    & schtasks.exe /Create /F /SC MINUTE /MO $Minutes /TN $taskName /TR $tr | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "schtasks failed (exit $LASTEXITCODE)" }
    "Installed scheduled task: $taskName (every $Minutes min, schtasks)"
}

if ($StartNow) {
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 5
}
$info = Get-ScheduledTaskInfo -TaskName $taskName
$info | Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime | Format-List