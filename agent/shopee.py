"""Shopee Affiliate Open API (Việt Nam).

Tài liệu gốc: https://affiliate.shopee.vn/open_api
Chữ ký theo tài liệu Shopee: SHA256(AppId + Timestamp + Payload + Secret),
gửi trong header:  Authorization: SHA256 Credential=<AppId>, Timestamp=<ts>, Signature=<hex>
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import requests

from .config import env

ENDPOINT = "https://open-api.affiliate.shopee.vn/graphql"

PRODUCT_FIELDS = """
  itemId shopId productName shopName
  priceMin priceMax priceDiscountRate
  commissionRate commission sales ratingStar
  imageUrl productLink offerLink
"""


class ShopeeError(RuntimeError):
    pass


def resolve_short_link(url: str) -> str:
    """s.shopee.vn/xxx hoặc shp.ee/xxx -> link sản phẩm đầy đủ."""
    if re.search(r"-i\.\d+\.\d+|/product/\d+/\d+", url):
        return url
    r = requests.get(url, allow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    return r.url


def parse_ids(url: str) -> tuple[int, int]:
    """Trả về (shop_id, item_id) từ link sản phẩm Shopee."""
    m = re.search(r"-i\.(\d+)\.(\d+)", url) or re.search(r"/product/(\d+)/(\d+)", url)
    if not m:
        raise ShopeeError(f"Không đọc được shop_id/item_id từ link: {url}")
    return int(m.group(1)), int(m.group(2))


def _call(query: str) -> dict:
    app_id, secret = env("SHOPEE_APP_ID"), env("SHOPEE_SECRET")
    if not app_id or not secret:
        raise ShopeeError("Thiếu SHOPEE_APP_ID hoặc SHOPEE_SECRET trong .env")
    payload = json.dumps({"query": query}, separators=(",", ":"), ensure_ascii=False)
    ts = str(int(time.time()))
    signature = hashlib.sha256(f"{app_id}{ts}{payload}{secret}".encode("utf-8")).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id}, Timestamp={ts}, Signature={signature}",
    }
    r = requests.post(ENDPOINT, data=payload.encode("utf-8"), headers=headers, timeout=20)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise ShopeeError(json.dumps(body["errors"], ensure_ascii=False))
    return body["data"]


def product_offer(shop_id: int, item_id: int) -> dict:
    q = f"{{ productOfferV2(shopId: {shop_id}, itemId: {item_id}, limit: 1) {{ nodes {{ {PRODUCT_FIELDS} }} }} }}"
    nodes = _call(q)["productOfferV2"]["nodes"]
    if not nodes:
        raise ShopeeError("Sản phẩm không nằm trong chương trình affiliate hoặc không tồn tại")
    return nodes[0]


def short_link(origin_url: str, sub_id: str = "") -> str:
    sub = f', subIds: ["{sub_id}"]' if sub_id else ""
    q = f'mutation {{ generateShortLink(input: {{ originUrl: "{origin_url}"{sub} }}) {{ shortLink }} }}'
    return _call(q)["generateShortLink"]["shortLink"]
