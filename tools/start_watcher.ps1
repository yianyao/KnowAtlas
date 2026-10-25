# Start/stop the resident context watcher (hidden window, logs under ~/.knowatlas/)
# Usage:
#   powershell -NoProfile -File tools/start_watcher.ps1
#   powershell -NoProfile -File tools/start_watcher.ps1 -Stop
#   powershell -NoProfile -File tools/start_watcher.ps1 -Interval 60
# NOTE: ASCII only. Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI,
#       so non-ASCII text here would be mojibake and can break quoting.
param(
    [int]$Interval = 60,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $env:USERPROFILE '.knowatlas'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$pidFile = Join-Path $stateDir 'watcher.pid'
$outLog = Join-Path $stateDir 'watcher.out.log'
$errLog = Join-Path $stateDir 'watcher.err.log'

function Get-WatcherPid {
    if (-not (Test-Path $pidFile)) { return $null }
    $text = (Get-Content $pidFile -Raw).Trim()
    if (-not $text) { return $null }
    return [int]$text
}

if ($Stop) {
    $watcherPid = Get-WatcherPid
    if ($watcherPid -and (Get-Process -Id $watcherPid -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $watcherPid -Force
        "Stopped watcher (PID $watcherPid)"
    } else {
        "No watcher process found"
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    return
}

$existing = Get-WatcherPid
if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
    "Watcher already running: PID $existing (use -Stop to restart)"
    return
}

$uv = (Get-Command uv -ErrorAction Stop).Source
$script = Join-Path $root 'tools\context_watcher.py'
$proc = Start-Process -FilePath $uv `
    -ArgumentList @('run', '--with', 'zstandard', 'python', $script,
        '--interval', "$Interval", '--workspace', $root) `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru
$proc.Id | Set-Content -Path $pidFile -Encoding ascii
"Watcher started: PID $($proc.Id)  interval=${Interval}s"
"stdout: $outLog"
"stderr: $errLog"