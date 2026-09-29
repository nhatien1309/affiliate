#!/usr/bin/env bash
# Hook SessionStart của Claude Code (khai báo trong .claude/settings.json): cho các lệnh Bash của Claude
# dùng Python trong .venv, để "python -m agent ..." có đủ thư viện và đọc được .env.
# macOS/Linux: .venv/bin, Windows (Git Bash): .venv/Scripts. Chưa có .venv thì không làm gì.
root="$(cd "$(dirname "$0")/.." && pwd)"
[ -n "$CLAUDE_ENV_FILE" ] || exit 0
for bin in "$root/.venv/bin" "$root/.venv/Scripts"; do
  if [ -d "$bin" ]; then
    printf 'export VIRTUAL_ENV="%s"\nexport PATH="%s:$PATH"\n' "$root/.venv" "$bin" >> "$CLAUDE_ENV_FILE"
    break
  fi
done
exit 0
