@echo off
rem Mo giao dien dieu khien (Windows): nhap dup file nay. Giu cua so mo trong luc dung.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Chua co .venv. Lam theo README muc 1 truoc.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m agent ui
pause
