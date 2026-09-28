# Sao lưu .env thành env.backup rồi đẩy lên GitHub. Chỉ chạy khi repo đang RIÊNG TƯ.
# Chạy lại mỗi khi sửa .env:  powershell -ExecutionPolicy Bypass -File scripts\sao_luu_env.ps1
# Khôi phục ở máy khác:        copy env.backup .env
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path .env)) { Write-Host "DỪNG: chưa có file .env"; exit 1 }

# gọi git.exe thay vì git: máy này có file rỗng C:\WINDOWS\system32\git che mất git thật
$remote = git.exe remote get-url origin
if ($remote -notmatch "github\.com[/:](.+?)(\.git)?$") { Write-Host "DỪNG: không đọc được repo GitHub từ $remote"; exit 1 }
$repo = $Matches[1]

# API GitHub trả 404 cho người lạ khi repo riêng tư; mọi kết quả khác đều coi là chưa an toàn
$code = try { (Invoke-WebRequest -UseBasicParsing -Uri "https://api.github.com/repos/$repo" -TimeoutSec 20).StatusCode } catch { $_.Exception.Response.StatusCode.value__ }
if ($code -ne 404) {
    Write-Host "DỪNG: repo $repo đang công khai hoặc không kiểm tra được (mã $code)."
    Write-Host "Vào GitHub -> repo -> Settings -> Change visibility -> Private, rồi chạy lại."
    exit 1
}

Copy-Item .env env.backup -Force
git.exe add env.backup
git.exe diff --cached --quiet -- env.backup
if ($LASTEXITCODE -eq 0) { Write-Host "env.backup không đổi, không cần đẩy."; exit 0 }
git.exe commit -q -m "Cập nhật env.backup" -- env.backup
git.exe push -q
Write-Host "Đã sao lưu .env lên $repo (file env.backup)."
