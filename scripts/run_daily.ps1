# Chạy agent hằng ngày trên Windows. Dùng với Task Scheduler (xem README).
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\.venv\Scripts\Activate.ps1"
New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null
$log = "$root\logs\$(Get-Date -Format 'yyyy-MM-dd').log"
claude -p "/chay-hang-ngay" *>> $log
