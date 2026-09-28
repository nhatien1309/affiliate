"""Tạo thư mục làm việc cho một sản phẩm: work/<slug>/product.json + images/."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import requests

from . import shopee
from .config import WORK_DIR, env
from .queue_store import platform_of


def slugify(text: str, max_len: int = 40) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "san-pham"


def format_vnd(value) -> str:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return ""
    return f"{n:,}".replace(",", ".") + "đ"


def _download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except requests.RequestException:
        return False


def workdir(slug: str) -> Path:
    return WORK_DIR / slug


def load(slug: str) -> dict:
    return json.loads((workdir(slug) / "product.json").read_text(encoding="utf-8"))


def _merge(old: dict, new: dict) -> dict:
    """Chạy lại fetch không làm mất phần đã điền tay: dữ liệu mới chỉ ghi đè khi không rỗng."""
    merged = dict(old)
    for k, v in new.items():
        if k == "needs" or v in (None, "", []):
            continue
        if k == "affiliate_link" and old.get(k):
            continue  # giữ link affiliate đã có (tự tạo tay hoặc tạo ở lần trước)
        merged[k] = v
    # việc còn thiếu: giữ bản agent đã cập nhật, trừ khi lần này đã lấy đủ dữ liệu
    merged["needs"] = old.get("needs", new["needs"]) if new["needs"] else []
    return merged


def fetch(url: str, slug: str | None = None) -> Path:
    platform = platform_of(url)
    product = {
        "source_url": url,
        "platform": platform,
        "name": None,
        "price_min": None,
        "price_max": None,
        "price_text": None,
        "commission_rate": None,
        "rating": None,
        "sales": None,
        "shop_name": None,
        "affiliate_link": None,
        "features": [],
        "needs": [],
    }

    if platform == "shopee" and env("SHOPEE_APP_ID"):
        full = shopee.resolve_short_link(url)
        shop_id, item_id = shopee.parse_ids(full)
        offer = shopee.product_offer(shop_id, item_id)
        product.update(
            name=offer.get("productName"),
            price_min=offer.get("priceMin"),
            price_max=offer.get("priceMax"),
            price_text=format_vnd(offer.get("priceMin")),
            commission_rate=offer.get("commissionRate"),
            rating=offer.get("ratingStar"),
            sales=offer.get("sales"),
            shop_name=offer.get("shopName"),
            image_url=offer.get("imageUrl"),
        )
        try:
            product["affiliate_link"] = shopee.short_link(full, sub_id="agent")
        except shopee.ShopeeError:
            product["affiliate_link"] = offer.get("offerLink")
    elif platform == "shopee":
        product["needs"].append(
            "Chưa có SHOPEE_APP_ID: dán link affiliate tự tạo trên affiliate.shopee.vn vào affiliate_link, "
            "điền tên, giá, và đặt ảnh sản phẩm vào images/"
        )
    elif platform == "tiktok":
        product["affiliate_link"] = url
        product["needs"].append(
            "TikTok Shop: đặt 3-5 ảnh chụp màn hình trang sản phẩm vào images/, "
            "agent đọc ảnh để điền tên, giá, điểm nổi bật"
        )

    slug = slug or slugify(product["name"] or url.rstrip("/").split("/")[-1])
    folder = workdir(slug)
    images = folder / "images"
    images.mkdir(parents=True, exist_ok=True)
    if product.get("image_url") and not any(images.iterdir()):
        _download(product["image_url"], images / "01.jpg")
    product["slug"] = slug
    path = folder / "product.json"
    if path.exists():
        product = _merge(json.loads(path.read_text(encoding="utf-8")), product)
    path.write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder
