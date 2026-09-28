"""Tìm sản phẩm đáng làm video qua Shopee Affiliate Open API, chấm điểm, lọc, rồi thêm vào hàng đợi.

Ý tưởng chấm điểm và lọc deal lấy từ auto-aff (aphuong2k), nhưng mã viết lại từ đầu và CHỈ dùng
Open API chính thức (không dùng cookie đăng nhập, không cào trang Shopee, không tự vào group Facebook).

Điểm (0-100):
  40  lượt bán (thang log, 10.000 lượt bán = đủ điểm)
  30  hoa hồng ước tính mỗi đơn (30.000đ = đủ điểm)
  20  điểm đánh giá (4,5 -> 0, 5,0 -> đủ điểm)
  10  mức giảm giá (50% = đủ điểm)
Loại ngay nếu: đánh giá dưới ngưỡng, bán quá ít, hoặc tên có từ thuộc nhóm cấm/nhạy cảm (CLAUDE.md).
"""
from __future__ import annotations

import json
import math
import re

from . import queue_store, shopee
from .product import format_vnd, slugify

SORT = {"lien-quan": 1, "ban-chay": 2, "hoa-hong": 5}
LIST = {"goi-y": 0, "hoa-hong-cao": 1, "hieu-qua": 2}

# khớp theo chữ không dấu; agent vẫn đọc lại từng sản phẩm trước khi làm video
BANNED = [
    "thuoc", "thuc pham chuc nang", "tpcn", "vien uong", "giam can", "tang can", "tri mun", "tri nam",
    "dac tri", "chua benh", "chua khoi", "sinh ly", "tang size", "bao cao su", "do choi nguoi lon",
    "vape", "thuoc la", "ruou", "dao gam", "sung hoi", "sung ban dan", "phi tieu", "cua quyen", "dui cui",
    "sua cho be", "sua bot",
]

FIELDS = """
  itemId shopId productName shopName productLink offerLink imageUrl
  priceMin priceMax priceDiscountRate sales ratingStar commissionRate commission
"""


def _plain(text: str) -> str:
    return slugify(text or "", max_len=500).replace("-", " ")


def banned_word(name: str) -> str | None:
    plain = f" {_plain(name)} "
    for w in BANNED:
        if f" {w} " in plain:
            return w
    return None


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def score(node: dict) -> tuple[float, dict]:
    price = _f(node.get("priceMin"))
    rate = _f(node.get("commissionRate"))
    rate = rate / 100 if rate > 1 else rate  # phòng khi API trả phần trăm thay vì tỉ lệ
    commission = _f(node.get("commission")) or price * rate
    sales = _f(node.get("sales"))
    rating = _f(node.get("ratingStar"))
    discount = _f(node.get("priceDiscountRate"))
    parts = {
        "ban": 40 * min(1.0, math.log10(1 + sales) / 4),
        "hoa_hong": 30 * min(1.0, commission / 30000),
        "danh_gia": 20 * max(0.0, min(1.0, (rating - 4.5) / 0.5)),
        "giam_gia": 10 * min(1.0, discount / 50),
    }
    info = {"price": price, "rate": rate, "commission": commission, "sales": sales,
            "rating": rating, "discount": discount}
    return round(sum(parts.values()), 1), info


def search(keyword: str | None, sort: str = "ban-chay", list_type: str | None = None,
           limit: int = 50, page: int = 1) -> list[dict]:
    args = [f"page: {int(page)}", f"limit: {int(limit)}"]
    if keyword:
        args.append(f"keyword: {json.dumps(keyword, ensure_ascii=False)}")
        args.append(f"sortType: {SORT[sort]}")
    else:
        args.append(f"listType: {LIST[list_type or 'hieu-qua']}")
        args.append(f"sortType: {SORT[sort]}")
    q = f"{{ productOfferV2({', '.join(args)}) {{ nodes {{ {FIELDS} }} }} }}"
    return shopee._call(q)["productOfferV2"]["nodes"] or []


def _queued_ids() -> set[tuple[int, int]]:
    ids = set()
    for r in queue_store.load():
        m = re.search(r"-i\.(\d+)\.(\d+)", r["url"]) or re.search(r"/product/(\d+)/(\d+)", r["url"])
        if m:
            ids.add((int(m.group(1)), int(m.group(2))))
    return ids


def rank(nodes: list[dict], min_rating: float = 4.5, min_sales: int = 50) -> tuple[list[dict], list[dict]]:
    """Trả về (đạt, bị loại). Mỗi phần tử có score, lý do, thông tin gọn để in."""
    queued = _queued_ids()
    ok, skipped, seen = [], [], set()
    for n in nodes:
        key = (int(_f(n.get("shopId"))), int(_f(n.get("itemId"))))
        if key in seen:
            continue
        seen.add(key)
        s, info = score(n)
        row = {
            "score": s,
            "name": n.get("productName"),
            "shop": n.get("shopName"),
            "price": format_vnd(info["price"]),
            "commission_rate": f"{info['rate'] * 100:.1f}%",
            "commission_est": format_vnd(info["commission"]),
            "sales": int(info["sales"]),
            "rating": info["rating"],
            "discount": f"{int(info['discount'])}%" if info["discount"] else "",
            "url": n.get("productLink") or f"https://shopee.vn/product/{key[0]}/{key[1]}",
        }
        reason = None
        if key in queued:
            reason = "đã có trong hàng đợi"
        elif (w := banned_word(row["name"])):
            reason = f"nhóm cấm/nhạy cảm (từ '{w}')"
        elif info["rating"] < min_rating:
            reason = f"đánh giá {info['rating']} < {min_rating}"
        elif info["sales"] < min_sales:
            reason = f"mới bán {int(info['sales'])} < {min_sales}"
        if reason:
            row["reason"] = reason
            skipped.append(row)
        else:
            ok.append(row)
    ok.sort(key=lambda r: r["score"], reverse=True)
    return ok, skipped


def add_to_queue(rows: list[dict], keyword: str | None) -> list[dict]:
    added = []
    for r in rows:
        note = (f"deal{' ' + keyword if keyword else ''}: điểm {r['score']} · hoa hồng {r['commission_rate']} "
                f"(~{r['commission_est']}) · đã bán {r['sales']} · {r['rating']}★")
        try:
            added.append(queue_store.add(r["url"], note))
        except ValueError:
            pass  # trùng link
    return added
