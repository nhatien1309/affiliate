"""Dòng lệnh của agent. Chạy: python -m agent <lệnh> ...

  python -m agent doctor                       kiểm tra cài đặt
  python -m agent queue add <link> [--note ..]  thêm link vào hàng đợi
  python -m agent queue list [--status moi]     xem hàng đợi
  python -m agent queue set <id> <trạng thái> [--note ..] [--slug ..]
  python -m agent fetch <link> [--slug ..]      tạo work/<slug>/ với product.json và ảnh
  python -m agent render <slug> [--platform facebook|tiktok|both] [--tts edge|elevenlabs|fpt|silent]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from . import queue_store
from .config import ROOT, env, font


def cmd_doctor(_args) -> int:
    ok = True

    def check(name, cond, hint=""):
        nonlocal ok
        print(("  OK   " if cond else "  THIẾU ") + name + ("" if cond else f"  → {hint}"))
        ok = ok and cond

    print("Kiểm tra cài đặt:")
    check("ffmpeg", bool(shutil.which("ffmpeg")), "cài ffmpeg (xem README)")
    check("ffprobe", bool(shutil.which("ffprobe")), "đi kèm ffmpeg")
    try:
        font("Bold")
        check("font tiếng Việt", True)
    except FileNotFoundError as e:
        check("font tiếng Việt", False, str(e))
    check("file .env", (ROOT / ".env").exists(), "copy .env.example thành .env")
    provider = env("TTS_PROVIDER", "edge")
    print(f"  Giọng đọc đang dùng: {provider}")
    if provider == "edge":
        try:
            import edge_tts  # noqa: F401
            check("edge-tts", True)
        except ImportError:
            check("edge-tts", False, "pip install edge-tts")
    elif provider == "elevenlabs":
        check("ELEVENLABS_API_KEY", bool(env("ELEVENLABS_API_KEY")), "điền vào .env")
        check("ELEVENLABS_VOICE_ID", bool(env("ELEVENLABS_VOICE_ID")), "điền vào .env")
    elif provider == "fpt":
        check("FPT_API_KEY", bool(env("FPT_API_KEY")), "điền vào .env")
    has_shopee = bool(env("SHOPEE_APP_ID") and env("SHOPEE_SECRET"))
    print("  Shopee Open API: " + ("đã cấu hình" if has_shopee else "chưa có (vẫn chạy được, nhập tay link affiliate)"))
    print("Kết quả: " + ("sẵn sàng" if ok else "cần bổ sung các mục THIẾU"))
    return 0 if ok else 1


def cmd_queue(args) -> int:
    if args.action == "add":
        row = queue_store.add(args.url, args.note or "")
        print(f"Đã thêm id {row['id']} ({row['platform']})")
    elif args.action == "list":
        rows = queue_store.load()
        if args.status:
            rows = [r for r in rows if r["status"] == args.status]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.action == "set":
        row = queue_store.set_status(args.id, args.status, args.note, args.slug)
        print(f"id {row['id']} → {row['status']}")
    return 0


def cmd_fetch(args) -> int:
    from .product import fetch
    folder = fetch(args.url, args.slug)
    print(json.dumps({"folder": str(folder), "product": json.loads((folder / "product.json").read_text(encoding="utf-8"))},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_render(args) -> int:
    from .render import render
    platforms = ["facebook", "tiktok"] if args.platform == "both" else [args.platform]
    for p in platforms:
        out = render(args.slug, p, args.tts)
        print(f"Xong {p}: {out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Agent tiếp thị liên kết")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)

    q = sub.add_parser("queue")
    q.add_argument("action", choices=["add", "list", "set"])
    q.add_argument("url_or_id", nargs="?")
    q.add_argument("status_value", nargs="?")
    q.add_argument("--note")
    q.add_argument("--status")
    q.add_argument("--slug")
    q.set_defaults(func=cmd_queue)

    f = sub.add_parser("fetch")
    f.add_argument("url")
    f.add_argument("--slug")
    f.set_defaults(func=cmd_fetch)

    r = sub.add_parser("render")
    r.add_argument("slug")
    r.add_argument("--platform", default="both", choices=["facebook", "tiktok", "both"])
    r.add_argument("--tts", choices=["edge", "elevenlabs", "fpt", "silent"])
    r.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    if args.cmd == "queue":
        args.url = args.id = args.url_or_id
        if args.action == "set":
            args.status = args.status_value
        if args.action in ("add", "set") and not args.url_or_id:
            parser.error("thiếu link hoặc id")
    try:
        return args.func(args)
    except Exception as e:  # báo lỗi gọn cho người dùng và cho Claude đọc
        print(f"LỖI: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
