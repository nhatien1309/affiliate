"""Đọc cấu hình từ .env và brand/brand.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # chạy được cả khi chưa cài python-dotenv
    def load_dotenv(*_a, **_k):
        return False

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

WORK_DIR = ROOT / "work"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MUSIC_DIR = ASSETS_DIR / "music"
QUEUE_FILE = ROOT / "queue.csv"
BRAND_FILE = ROOT / "brand" / "brand.json"


def reload_env() -> None:
    """Đọc lại .env: giao diện chạy lâu, chủ dự án có thể vừa thêm khóa API."""
    load_dotenv(ROOT / ".env", override=True)


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is not None:
        value = value.strip()
    return value or default


def brand() -> dict:
    defaults = {
        "handle": "@tencuaban",
        "accent": "#0F766E",
        "accent_text": "#FFFFFF",
        "price_bg": "#FFD23F",
        "price_text": "#16201E",
        "caption_color": "#FFFFFF",
        "caption_stroke": "#000000",
        "music_volume": 0.12,
        "disclosure": "Link tiếp thị liên kết: mình nhận hoa hồng nếu bạn mua qua link, giá không đổi.",
        "show_price": False,  # hiện giá trong video; bật/tắt trên giao diện điều khiển
    }
    if BRAND_FILE.exists():
        defaults.update(json.loads(BRAND_FILE.read_text(encoding="utf-8")))
    return defaults


def update_brand(**changes) -> dict:
    """Ghi vài mục vào brand/brand.json, giữ nguyên các mục khác."""
    data = json.loads(BRAND_FILE.read_text(encoding="utf-8")) if BRAND_FILE.exists() else {}
    data.update(changes)
    BRAND_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return brand()


def font(weight: str = "Bold") -> str:
    path = FONTS_DIR / f"BeVietnamPro-{weight}.ttf"
    if path.exists():
        return str(path)
    # dự phòng: font hệ thống có dấu tiếng Việt
    for candidate in (
        "C:/Windows/Fonts/arialbd.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Không tìm thấy font. Đặt BeVietnamPro-Bold.ttf vào assets/fonts/")
