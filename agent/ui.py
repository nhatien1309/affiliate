"""Giao diện điều khiển chạy trên máy: python -m agent ui  →  http://127.0.0.1:8765

Dán link, bấm nút thay cho gõ lệnh, xem log từng lệnh theo thời gian thực, xem video đã dựng.
- Chỉ nghe ở 127.0.0.1. Mọi yêu cầu phải có Host là 127.0.0.1/localhost, lệnh POST phải kèm token
  sinh ngẫu nhiên mỗi lần mở (nhúng trong trang), để trang web lạ không kích hoạt lệnh được.
- Lệnh chạy lần lượt từng cái (hàng chờ lệnh) để không ghi đè queue.csv / output/ của nhau.
- Lệnh Claude chạy như lịch hằng ngày: claude -p "/lệnh ..." với quyền trong .claude/settings.json.
- Chỉ gửi ra trang các cài đặt không bí mật; khóa API trong .env không bao giờ rời máy chủ.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import queue_store, tts
from .config import OUTPUT_DIR, ROOT, WORK_DIR, brand, reload_env, update_brand

try:
    from dotenv import dotenv_values
except ImportError:  # chạy được cả khi chưa cài python-dotenv
    def dotenv_values(*_a, **_k):
        return {}

STATIC_DIR = Path(__file__).parent / "ui_static"
FONTS_DIR = ROOT / "assets" / "fonts"
LOG_DIR = ROOT / "logs"
UI_LOG_DIR = LOG_DIR / "ui"
TASK_NAME = "Affiliate agent"  # tác vụ Task Scheduler (README mục 4)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
ID_RE = re.compile(r"^[0-9a-f]{6}$")
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
RATE_RE = re.compile(r"^[+-]\d{1,2}%$")
PITCH_RE = re.compile(r"^[+-]\d{1,2}Hz$")
EL_VOICE_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")
PREVIEW_DIR = "_nghe-thu"  # trong output/; bắt đầu bằng "_" nên không hiện thành sản phẩm
PREVIEW_TEXT = "Chào anh em, đây là giọng đọc thử cho video của kênh. Nghe vậy có ổn không nè?"
PLATFORMS = ("facebook", "tiktok")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
DONE = ("xong", "loi", "da_dung")
DONE_TEXT = {"xong": "Xong", "loi": "Lỗi", "da_dung": "Đã dừng"}
SETTINGS = {  # chỉ các mục không bí mật
    "APPROVAL_MODE": "duyet_tung_video", "MAX_PER_DAY": "2", "TIKTOK_HAS_CART": "false",
    "VIDEO_ENGINE": "ffmpeg", "TTS_PROVIDER": "edge",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".srt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".ttf": "font/ttf", ".wav": "audio/wav", ".mp3": "audio/mpeg",
}


# ---------- hàng chờ lệnh ----------

class Job:
    def __init__(self, title: str, cmd: list[str], kind: str):
        self.id = secrets.token_hex(4)
        self.title, self.cmd, self.kind = title, cmd, kind  # kind: "claude" | "python"
        self.status = "cho"  # cho | dang_chay | xong | loi | da_dung
        self.lines: list[dict] = []
        self.created = time.time()
        self.started: float | None = None
        self.ended: float | None = None
        self.returncode: int | None = None
        self.proc: subprocess.Popen | None = None
        self.failed = False
        self.stopping = False
        self._log = None

    def add(self, kind: str, text: str) -> None:
        for part in str(text).splitlines() or [""]:
            self.lines.append({"k": kind, "s": part})
            if self._log:
                self._log.write(part + "\n")
                self._log.flush()

    def summary(self, position: int = 0) -> dict:
        return {"id": self.id, "title": self.title, "kind": self.kind, "status": self.status,
                "created": self.created, "started": self.started, "ended": self.ended,
                "returncode": self.returncode, "lines": len(self.lines), "position": position}


class Runner:
    """Chạy lệnh lần lượt trong một luồng riêng; giữ log trong bộ nhớ và trong logs/ui/."""
    keep = 50

    def __init__(self):
        self.jobs: list[Job] = []
        self._pending: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, title: str, cmd: list[str], kind: str) -> Job:
        job = Job(title, cmd, kind)
        with self._lock:
            self.jobs.append(job)
            extra = len(self.jobs) - self.keep
            for old in [j for j in self.jobs if j.status in DONE][:max(0, extra)]:
                self.jobs.remove(old)
        self._pending.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def summaries(self) -> list[dict]:
        with self._lock:
            jobs = list(self.jobs)
        return [j.summary(self.position(j)) for j in reversed(jobs)]

    def position(self, job: Job) -> int:
        """Thứ tự trong hàng chờ (1 = chạy kế tiếp); 0 nếu đang chạy hoặc đã xong."""
        with self._lock:
            waiting = [j for j in self.jobs if j.status == "cho"]
        return waiting.index(job) + 1 if job in waiting else 0

    def stop(self, job: Job) -> None:
        job.stopping = True
        if job.status == "cho":
            job.status, job.ended = "da_dung", time.time()
            job.add("info", "Đã hủy trước khi chạy.")
        elif job.proc and job.proc.poll() is None:
            _kill_tree(job.proc)

    def stop_all(self) -> None:
        for job in list(self.jobs):
            if job.status in ("cho", "dang_chay"):
                self.stop(job)

    def _loop(self) -> None:
        while True:
            job = self._pending.get()
            if job.status == "cho":
                self._run(job)

    def _run(self, job: Job) -> None:
        job.status, job.started = "dang_chay", time.time()
        try:
            UI_LOG_DIR.mkdir(parents=True, exist_ok=True)
            job._log = (UI_LOG_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{job.id}.log").open("w", encoding="utf-8")
        except OSError:
            job._log = None
        job.add("info", "$ " + _display(job))
        try:
            job.proc = subprocess.Popen(
                job.cmd, cwd=ROOT, env=_child_env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as e:
            job.add("err", f"Không chạy được lệnh: {e}")
            job.failed = True
        else:
            if job.stopping:  # bấm Dừng đúng lúc lệnh vừa khởi động
                _kill_tree(job.proc)
            for raw in job.proc.stdout:
                raw = raw.rstrip("\r\n")
                if job.kind == "claude":
                    lines, failed = claude_event(raw)
                    job.failed = job.failed or failed
                else:
                    lines = [(_python_kind(raw), raw)]
                for kind, text in lines:
                    job.add(kind, text)
            job.returncode = job.proc.wait()
        job.ended = time.time()
        if job.stopping:
            job.status = "da_dung"
        elif job.failed or job.returncode:
            job.status = "loi"
        else:
            job.status = "xong"
        job.add("info", f"— {DONE_TEXT[job.status]} sau {job.ended - job.started:.0f} giây")
        if job._log:
            job._log.close()
            job._log = None


def _kill_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":  # claude chạy nhiều tiến trình con; phải dừng cả cây
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()


def _child_env() -> dict:
    env = dict(os.environ)
    # bỏ các giá trị nạp từ .env: tiến trình Python tự đọc lại .env, còn Claude không cần thấy khóa API
    for key in dotenv_values(ROOT / ".env"):
        env.pop(key, None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")  # "python" = python của .venv
    if sys.prefix != sys.base_prefix:
        env["VIRTUAL_ENV"] = sys.prefix
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _display(job: Job) -> str:
    if job.kind == "claude":
        return f"claude -p {job.cmd[2]}"
    return "python " + " ".join(job.cmd[2:])


def _python_kind(line: str) -> str:
    if line.startswith(("LỖI", "Traceback")):
        return "err"
    if line.startswith("CẢNH BÁO"):
        return "warn"
    return "out"


def _short(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _tool_summary(inp: dict) -> str:
    for key in ("command", "file_path", "pattern", "description", "url", "query", "prompt"):
        if inp.get(key):
            return _short(inp[key], 160)
    return _short(json.dumps(inp, ensure_ascii=False), 160)


def claude_event(raw: str) -> tuple[list[tuple[str, str]], bool]:
    """Một dòng của `claude -p --output-format stream-json` → (các dòng log dễ đọc, có báo lỗi không)."""
    raw = raw.lstrip("﻿")
    try:
        ev = json.loads(raw)
    except ValueError:
        ev = None
    if not isinstance(ev, dict):  # ngoài luồng JSON: cảnh báo của Claude CLI, ví dụ chưa tin thư mục
        return ([("warn", raw)] if raw.strip() else []), False
    kind, out = ev.get("type"), []
    if kind == "system" and ev.get("subtype") == "init":
        out.append(("info", f"Claude bắt đầu (model {ev.get('model', '?')})"))
    elif kind in ("assistant", "user"):
        content = (ev.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if kind == "assistant" and block.get("type") == "text" and str(block.get("text", "")).strip():
                out.append(("text", block["text"].strip()))
            elif kind == "assistant" and block.get("type") == "tool_use":
                out.append(("tool", f"▸ {block.get('name')}: {_tool_summary(block.get('input') or {})}"))
            elif kind == "user" and block.get("type") == "tool_result" and block.get("is_error"):
                res = block.get("content")
                if isinstance(res, list):
                    res = " ".join(b.get("text", "") for b in res if isinstance(b, dict))
                out.append(("err", "✗ " + _short(res or "công cụ báo lỗi", 300)))
    elif kind == "result":
        for d in ev.get("permission_denials") or []:
            out.append(("warn", f"Bị chặn quyền: {d.get('tool_name')} {_tool_summary(d.get('tool_input') or {})}"))
        failed = bool(ev.get("is_error")) or ev.get("subtype") != "success"
        tail = f" · {(ev.get('duration_ms') or 0) / 1000:.0f} giây"
        if isinstance(ev.get("total_cost_usd"), (int, float)):
            tail += f" · ≈ ${ev['total_cost_usd']:.2f}"
        out.append(("err" if failed else "info", ("Claude báo lỗi" if failed else "Claude xong") + tail))
        if failed and ev.get("result"):
            out.append(("err", str(ev["result"])))
        return out, failed
    return out, False


# ---------- tạo lệnh từ nút bấm ----------

def _one_line(text, n: int = 200) -> str:
    return " ".join(str(text or "").split())[:n]


def _choice(value, allowed: tuple, what: str) -> str:
    if value not in allowed:
        raise ValueError(f"{what} không hợp lệ: {value}")
    return value


def _match(regex: re.Pattern, value, what: str) -> str:
    value = str(value or "")
    if not regex.match(value):
        raise ValueError(f"{what} không hợp lệ: {value}")
    return value


def _voice(p: dict) -> dict:
    """Giọng chọn trên trang → dict đã kiểm tra, để lưu vào brand.json hoặc nghe thử."""
    provider = _choice(p.get("provider"), ("edge", "elevenlabs", "fpt"), "Nhà cung cấp giọng")
    v = {"provider": provider}
    if provider == "edge":
        v["edge_voice"] = _choice(p.get("edge_voice"), tuple(c for c, _, _ in tts.EDGE_VOICES), "Giọng Edge")
        v["edge_rate"] = _match(RATE_RE, p.get("edge_rate") or "+0%", "Tốc độ")
        v["edge_pitch"] = _match(PITCH_RE, p.get("edge_pitch") or "+0Hz", "Cao độ")
    elif provider == "elevenlabs":
        v["elevenlabs_voice_id"] = _match(EL_VOICE_RE, p.get("elevenlabs_voice_id"), "Mã giọng ElevenLabs")
        v["elevenlabs_voice_name"] = _one_line(p.get("elevenlabs_voice_name"), 60)
    else:
        v["fpt_voice"] = _choice(p.get("fpt_voice"), tuple(c for c, _ in tts.FPT_VOICES), "Giọng FPT")
    return v


def voice_preview(v: dict) -> str:
    """Đọc câu mẫu bằng giọng v, trả về đường dẫn /media. Lưu theo mã băm: nghe lại không tốn thêm ký tự."""
    folder = OUTPUT_DIR / PREVIEW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([v, PREVIEW_TEXT], sort_keys=True).encode("utf-8")).hexdigest()[:16]
    dest = folder / f"{key}.wav"
    if not dest.exists():
        tmp = folder / f"{key}-{secrets.token_hex(3)}.tmp.wav"  # bấm hai lần liền không ghi đè nhau
        try:
            tts.synthesize(PREVIEW_TEXT, tmp, voice=v)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
    return _media("output", PREVIEW_DIR, dest.name)


_el_cache: dict = {"at": 0.0, "voices": None, "error": None}


def voice_lists(refresh: bool = False) -> dict:
    """Danh sách giọng cho menu. Giọng ElevenLabs lấy từ tài khoản, nhớ 10 phút."""
    reload_env()
    keys = {"elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")), "fpt": bool(os.getenv("FPT_API_KEY"))}
    if refresh or time.time() - _el_cache["at"] > 600:
        try:
            _el_cache.update(voices=tts.elevenlabs_voices(), error=None)
        except (tts.TTSError, OSError) as e:  # OSError gồm cả lỗi mạng của requests
            _el_cache.update(voices=None, error=str(e))
        _el_cache["at"] = time.time()
    return {
        "edge": [{"id": c, "name": n, "group": g} for c, n, g in tts.EDGE_VOICES],
        "fpt": [{"id": c, "name": n} for c, n in tts.FPT_VOICES],
        "elevenlabs": _el_cache["voices"], "elevenlabs_error": _el_cache["error"],
        "keys": keys, "preview_text": PREVIEW_TEXT,
    }


def _slug(params: dict) -> str:
    slug = str(params.get("slug") or "")
    if not SLUG_RE.match(slug) or not ((WORK_DIR / slug).is_dir() or (OUTPUT_DIR / slug).is_dir()):
        raise ValueError(f"Không có sản phẩm {slug!r}")
    return slug


def _claude(prompt: str) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise ValueError("Không tìm thấy lệnh claude. Cài Claude CLI rồi đăng nhập (README mục 1).")
    return [exe, "-p", prompt, "--output-format", "stream-json", "--verbose"]


def build_job(action, p: dict) -> tuple[str, list[str], str]:
    """Nút bấm → (tiêu đề, lệnh, loại). Mọi tham số từ trang đều được kiểm tra ở đây."""
    py = [sys.executable, "-u", "-m", "agent"]
    if action == "doctor":
        return "Kiểm tra cài đặt", py + ["doctor"], "python"
    if action == "render":
        slug = _slug(p)
        platform = _choice(p.get("platform") or "both", (*PLATFORMS, "both"), "Nền tảng")
        cmd = py + ["render", slug, "--platform", platform]
        if p.get("engine"):
            cmd += ["--engine", _choice(p["engine"], ("ffmpeg", "hyperframes"), "Kiểu dựng")]
        if p.get("tts"):
            cmd += ["--tts", _choice(p["tts"], ("edge", "elevenlabs", "fpt", "silent"), "Giọng đọc")]
        return f"Dựng {platform} · {slug}", cmd, "python"
    if action == "lam-video":
        target = _one_line(p.get("target"), 500)
        if not (ID_RE.match(target) or target.startswith(("http://", "https://"))):
            raise ValueError("Cần id trong hàng đợi hoặc link sản phẩm")
        return f"Làm video · {target}", _claude(f"/lam-video {target}"), "claude"
    if action == "chay-hang-ngay":
        return "Chạy phiên hằng ngày", _claude("/chay-hang-ngay"), "claude"
    if action == "tim-deal":
        keyword = _one_line(p.get("keyword"), 80)
        try:
            count = min(20, max(1, int(p.get("count") or 5)))
        except ValueError:
            count = 5
        prompt = f"/tim-deal từ khóa: {keyword or '(mặc định trong brand.json)'}, số lượng: {count}"
        return f"Tìm deal · {keyword or 'mặc định'}", _claude(prompt), "claude"
    if action == "duyet":
        slug = _slug(p)
        platform = _choice(p.get("platform") or "both", (*PLATFORMS, "both"), "Nền tảng")
        when = _one_line(p.get("time"), 40)
        return f"Duyệt {platform} · {slug}", _claude(f"/duyet {slug} {platform} {when}".strip()), "claude"
    if action == "bao-cao-tuan":
        return "Báo cáo tuần", _claude("/bao-cao-tuan"), "claude"
    raise ValueError(f"Lệnh không hợp lệ: {action}")


# ---------- dữ liệu cho trang ----------

def _settings() -> dict:
    vals = {k: (v or "").strip() for k, v in dotenv_values(ROOT / ".env").items()}
    out = {k: vals.get(k) or default for k, default in SETTINGS.items()}
    out["SHOW_PRICE"] = brand().get("show_price") is True
    voice = tts.voice_settings()
    out["VOICE"] = voice
    out["VOICE_LABEL"] = tts.describe(voice)
    out["SHOPEE_API"] = bool(vals.get("SHOPEE_APP_ID") and vals.get("SHOPEE_SECRET"))
    out["CLAUDE_CLI"] = bool(shutil.which("claude"))
    out["CLAUDE_TRUSTED"] = _claude_trusted()
    return out


_trust_cache: dict = {}


def _path_key(path: str) -> str:
    # macOS có thể lưu tên thư mục có dấu ("trọng") dạng NFD, còn ~/.claude.json ghi dạng NFC
    return unicodedata.normalize("NFC", path.replace("\\", "/")).rstrip("/").lower()


def _claude_trusted() -> bool | None:
    """Thư mục dự án đã được tin trong Claude Code chưa. Chưa tin thì `claude -p` bỏ qua quyền trong
    .claude/settings.json nên lệnh chạy tự động bị chặn. None = không đọc được ~/.claude.json."""
    path = Path.home() / ".claude.json"
    try:
        mtime = path.stat().st_mtime
        if _trust_cache.get("mtime") != mtime:
            projects = json.loads(path.read_text(encoding="utf-8")).get("projects") or {}
            trusted = {_path_key(k) for k, v in projects.items()
                       if isinstance(v, dict) and v.get("hasTrustDialogAccepted")}
            _trust_cache.update(mtime=mtime, trusted=trusted)
    except (OSError, ValueError, AttributeError):
        return None
    candidates = [ROOT, *ROOT.parents]  # tin thư mục cha cũng tính
    return any(_path_key(p.as_posix()) in _trust_cache["trusted"] for p in candidates)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _media(*parts: str) -> str:
    return "/media/" + "/".join(quote(p) for p in parts)


def _products(queue_rows: list[dict]) -> list[dict]:
    by_slug = {r["slug"]: r for r in queue_rows if r.get("slug")}
    slugs = set()
    for base in (WORK_DIR, OUTPUT_DIR):
        if base.is_dir():
            slugs |= {d.name for d in base.iterdir() if d.is_dir() and SLUG_RE.match(d.name)}
    items = []
    for slug in slugs:
        work = WORK_DIR / slug
        product = _read_json(work / "product.json")
        img_dir = work / "images"
        images = sorted(p.name for p in img_dir.iterdir() if p.suffix.lower() in IMAGE_EXT) if img_dir.is_dir() else []
        outputs, latest = {}, (work / "product.json").stat().st_mtime if (work / "product.json").exists() else 0
        for platform in PLATFORMS:
            out_dir = OUTPUT_DIR / slug / platform
            video = out_dir / "video.mp4"
            if not video.exists():
                continue
            mtime = video.stat().st_mtime
            latest = max(latest, mtime)
            outputs[platform] = {
                "video": _media("output", slug, platform, "video.mp4") + f"?v={int(mtime)}",
                "cover": _media("output", slug, platform, "cover.jpg") + f"?v={int(mtime)}"
                if (out_dir / "cover.jpg").exists() else None,
                "caption": _read_text(out_dir / "caption.txt"),
                "meta": _read_json(out_dir / "meta.json"),
                "built_at": mtime,
            }
        row = by_slug.get(slug)
        items.append({
            "slug": slug,
            "name": product.get("name") or slug,
            "price": product.get("price_text"),
            "platform": product.get("platform"),
            "needs": product.get("needs") or [],
            "scripts": [p for p in PLATFORMS if (work / f"script_{p}.json").exists()],
            "image": _media("work", slug, "images", images[0]) if images else None,
            "outputs": outputs,
            "queue": {k: row.get(k) for k in ("id", "status", "agent_note")} if row else None,
            "_latest": latest,
        })
    items.sort(key=lambda it: it.pop("_latest"), reverse=True)
    return items


def _daily_logs() -> list[str]:
    if not LOG_DIR.is_dir():
        return []
    return sorted((p.name for p in LOG_DIR.iterdir() if DAILY_RE.match(p.name)), reverse=True)[:14]


def _read_log(path: Path, max_lines: int = 400) -> str:
    data = path.read_bytes()
    # run_daily.ps1 ghi bằng Windows PowerShell 5.1 → UTF-16; run_daily.sh → UTF-8
    encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    lines = data.decode(encoding, errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


class _Schedule:
    """Giờ chạy tự động tiếp theo trong Task Scheduler; làm mới ngầm 5 phút/lần để trang không bị chậm."""

    def __init__(self):
        self.info: dict | None = None
        self._at = 0.0
        self._busy = False

    def get(self) -> dict | None:
        if sys.platform == "win32" and not self._busy and time.time() - self._at > 300:
            self._busy = True
            threading.Thread(target=self._refresh, daemon=True).start()
        return self.info

    def _refresh(self) -> None:
        ps = (f"$i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}' -ErrorAction Stop; "
              "$i.NextRunTime.ToString('s'); $i.LastRunTime.ToString('s'); $i.LastTaskResult")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20).stdout.split()
            self.info = {"next": out[0], "last": out[1], "result": int(out[2])} if len(out) == 3 else {"missing": True}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.info = None
        finally:
            self._at, self._busy = time.time(), False


def _inside(base: Path, *parts: str) -> Path | None:
    """File nằm trong base; None nếu có '..', ổ đĩa, hoặc trỏ ra ngoài."""
    if not parts or any(p in ("", ".", "..") or "/" in p or "\\" in p or ":" in p for p in parts):
        return None
    path = base.joinpath(*parts).resolve()
    return path if path.is_file() and base.resolve() in path.parents else None


def _open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — mở Explorer tại thư mục sản phẩm
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ---------- máy chủ ----------

class Handler(BaseHTTPRequestHandler):
    runner: Runner
    token: str
    schedule: _Schedule
    server_version = "AffiliateAgentUI"

    def log_message(self, *_a):  # không in từng yêu cầu ra terminal
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost")

    def _headers(self, code: int, ctype: str, length: int, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self._headers(code, ctype, len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    def _file(self, path: Path | None) -> None:
        if path is None:
            return self._error(404, "Không có file này")
        size = path.stat().st_size
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if m and size and (m.group(1) or m.group(2)):  # video cần Range để tua
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            code = 206
        cache = "private, max-age=86400" if path.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".ttf") else "no-cache"
        self._headers(code, ctype, end - start + 1 if size else 0, cache)
        self.send_header("Accept-Ranges", "bytes")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1 if size else 0
            while remaining > 0:
                chunk = f.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "Chỉ mở được từ chính máy này (127.0.0.1)")
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        try:
            if not parts:
                html = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", self.token)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            head = parts[0]
            if head == "static" and len(parts) == 2:
                return self._file(_inside(STATIC_DIR, parts[1]))
            if head == "fonts" and len(parts) == 2:
                return self._file(_inside(FONTS_DIR, parts[1]))
            if head == "media" and len(parts) > 2 and parts[1] in ("output", "work"):
                return self._file(_inside(OUTPUT_DIR if parts[1] == "output" else WORK_DIR, *parts[2:]))
            if parts == ["api", "state"]:
                rows = sorted(queue_store.load(), key=lambda r: r.get("created_at") or "", reverse=True)
                return self._json({"settings": _settings(), "schedule": self.schedule.get(), "queue": rows,
                                   "products": _products(rows), "jobs": self.runner.summaries(),
                                   "daily_logs": _daily_logs()})
            if parts == ["api", "voices"]:
                return self._json(voice_lists(refresh="refresh" in parse_qs(url.query)))
            if head == "api" and len(parts) == 3 and parts[1] == "jobs":
                job = self.runner.get(parts[2])
                if not job:
                    return self._error(404, "Không còn lệnh này")
                try:
                    since = max(0, int(parse_qs(url.query).get("since", ["0"])[0]))
                except ValueError:
                    since = 0
                lines = job.lines[since:]
                return self._json({"job": job.summary(), "lines": lines, "next": since + len(lines)})
            if head == "api" and len(parts) == 3 and parts[1] == "daily-log" and DAILY_RE.match(parts[2]):
                path = LOG_DIR / parts[2]
                if path.is_file():
                    return self._json({"name": parts[2], "text": _read_log(path)})
        except ConnectionError:  # trình duyệt bỏ ngang (tua video, đóng tab)
            return
        self._error(404, "Không có trang này")

    def do_POST(self):
        given = (self.headers.get("X-Token") or "").encode("utf-8", "replace")
        if not self._host_ok() or not secrets.compare_digest(given, self.token.encode()):
            return self._error(403, "Phiên đã hết hạn. Tải lại trang.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 65536:
                return self._error(413, "Dữ liệu quá lớn")
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            if not isinstance(body, dict):
                raise ValueError("Dữ liệu gửi lên không hợp lệ")
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            if parts == ["api", "queue", "add"]:
                return self._json(self._queue_add(body))
            if parts == ["api", "queue", "set"]:
                item_id = str(body.get("id") or "")
                if not ID_RE.match(item_id):
                    raise ValueError("id không hợp lệ")
                status = _choice(body.get("status"), ("moi", "bo_qua"), "Trạng thái")
                return self._json({"row": queue_store.set_status(item_id, status)})
            if parts == ["api", "settings"]:  # chỉ các mục trong brand.json, không đụng tới .env
                if not isinstance(body.get("show_price"), bool):
                    raise ValueError("show_price phải là true hoặc false")
                update_brand(show_price=body["show_price"])
                return self._json({"settings": _settings()})
            if parts == ["api", "voice"]:  # lưu vào brand.json, giữ lựa chọn cũ của các nhà cung cấp khác
                update_brand(voice={**(brand().get("voice") or {}), **_voice(body)})
                return self._json({"settings": _settings()})
            if parts == ["api", "voice", "preview"]:
                v = _voice(body)
                reload_env()
                try:
                    return self._json({"url": voice_preview(v)})
                except tts.TTSError as e:
                    return self._error(400, str(e))
                except Exception as e:  # noqa: BLE001 — lỗi mạng, ffmpeg...: báo lên trang thay vì làm rớt kết nối
                    return self._error(502, f"Không tạo được giọng đọc thử: {e}")
            if parts == ["api", "run"]:
                job = self.runner.submit(*build_job(body.get("action"), body))
                return self._json({"job": job.summary(self.runner.position(job))})
            if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "stop":
                job = self.runner.get(parts[2])
                if not job:
                    return self._error(404, "Không còn lệnh này")
                self.runner.stop(job)
                return self._json({"job": job.summary()})
            if parts == ["api", "open"]:
                slug = _slug(body)
                platform = body.get("platform")
                for path in ((OUTPUT_DIR / slug / platform) if platform in PLATFORMS else None,
                             OUTPUT_DIR / slug, WORK_DIR / slug):
                    if path and path.is_dir():
                        _open_folder(path)
                        return self._json({"path": str(path)})
                raise ValueError("Chưa có thư mục cho sản phẩm này")
        except PermissionError:
            return self._error(400, "Không ghi được file (queue.csv đang mở trong Excel?). Đóng file rồi thử lại.")
        except (ValueError, KeyError) as e:
            return self._error(400, str(e).strip("'\""))
        except ConnectionError:
            return
        self._error(404, "Không có lệnh này")

    def _queue_add(self, body: dict) -> dict:
        run_now = bool(body.get("run"))
        if run_now and not shutil.which("claude"):
            raise ValueError("Không tìm thấy lệnh claude. Cài Claude CLI rồi đăng nhập (README mục 1).")
        row = queue_store.add(_one_line(body.get("url"), 1000), _one_line(body.get("note"), 200))
        job = self.runner.submit(*build_job("lam-video", {"target": row["id"]})) if run_now else None
        return {"row": row, "job": job.summary() if job else None}


class _Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"  # Windows: không cho hai giao diện chiếm chung một cổng
    daemon_threads = True


def make_server(port: int = 8765) -> tuple[_Server, str, Runner]:
    runner = Runner()
    token = secrets.token_urlsafe(24)
    handler = type("BoundHandler", (Handler,), {"runner": runner, "token": token, "schedule": _Schedule()})
    return _Server(("127.0.0.1", port), handler), token, runner


def serve(port: int = 8765, open_browser: bool = True) -> int:
    try:
        httpd, _token, runner = make_server(port)
    except OSError as e:
        raise RuntimeError(f"Không mở được cổng {port}, có thể giao diện đang chạy ở cửa sổ khác ({e})") from e
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Giao diện điều khiển: {url}")
    print("Giữ cửa sổ này mở trong lúc dùng. Tắt: Ctrl+C hoặc đóng cửa sổ.")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Đã tắt giao diện.")
    finally:
        runner.stop_all()
        httpd.server_close()
    return 0
