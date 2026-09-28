#!/usr/bin/env bash
# Chạy agent hằng ngày trên macOS/Linux. Dùng với cron (xem README).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
source .venv/bin/activate
mkdir -p logs
claude -p "/chay-hang-ngay" >> "logs/$(date +%F).log" 2>&1
