"""Hàng đợi sản phẩm lưu trong queue.csv (mở được bằng Excel)."""
from __future__ import annotations

import csv
import uuid
from datetime import datetime
from urllib.parse import urlparse

from .config import QUEUE_FILE

FIELDS = ["id", "url", "platform", "note", "status", "slug", "created_at", "updated_at", "agent_note"]
STATUSES = ["moi", "dang_lam", "cho_duyet", "da_len_lich", "da_dang", "bo_qua", "loi"]


def platform_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "shopee" in host or host.endswith("shp.ee"):
        return "shopee"
    if host.endswith("tiktok.com"):
        return "tiktok"
    return "khac"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    with QUEUE_FILE.open(encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def save(rows: list[dict]) -> None:
    with QUEUE_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def add(url: str, note: str = "") -> dict:
    url = url.strip()
    if not url.startswith("http"):
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https://")
    rows = load()
    for r in rows:
        if r["url"] == url:
            raise ValueError(f"Link đã có trong hàng đợi (id {r['id']}, trạng thái {r['status']})")
    row = {
        "id": uuid.uuid4().hex[:6],
        "url": url,
        "platform": platform_of(url),
        "note": note,
        "status": "moi",
        "created_at": _now(),
        "updated_at": _now(),
    }
    rows.append(row)
    save(rows)
    return row


def set_status(item_id: str, status: str, agent_note: str | None = None, slug: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"Trạng thái không hợp lệ. Dùng một trong: {', '.join(STATUSES)}")
    rows = load()
    for r in rows:
        if r["id"] == item_id:
            r["status"] = status
            r["updated_at"] = _now()
            if agent_note is not None:
                r["agent_note"] = agent_note
            if slug is not None:
                r["slug"] = slug
            save(rows)
            return r
    raise KeyError(f"Không có id {item_id} trong hàng đợi")


def pending(status: str = "moi") -> list[dict]:
    return [r for r in load() if r.get("status") == status]
