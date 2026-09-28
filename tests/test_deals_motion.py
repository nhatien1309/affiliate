"""Chạy: python -m unittest discover tests
Không gọi mạng: API Shopee được giả lập."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import deals, motion, queue_store


def node(item, name, price=200000, rate="0.08", sales=1200, rating="4.8", discount=20):
    return {"itemId": item, "shopId": 99, "productName": name, "shopName": "Shop A",
            "productLink": f"https://shopee.vn/product/99/{item}", "priceMin": str(price),
            "commissionRate": rate, "commission": "", "sales": sales, "ratingStar": rating,
            "priceDiscountRate": discount}


class DealsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = mock.patch.object(queue_store, "QUEUE_FILE", Path(self.tmp.name) / "queue.csv")
        self.q.start()

    def tearDown(self):
        self.q.stop()
        self.tmp.cleanup()

    def test_rank_filters_and_orders(self):
        nodes = [
            node(1, "Tai nghe bluetooth chống ồn", sales=9000),
            node(2, "Sạc dự phòng 10000mAh", sales=300, rating="4.9"),
            node(3, "Viên uống giảm cân thảo mộc"),                 # nhóm cấm
            node(4, "Bàn phím cơ", rating="4.2"),                    # đánh giá thấp
            node(5, "Chuột không dây", sales=10),                    # bán ít
            node(6, "Kệ đỡ laptop bổ sung phụ kiện kiểm tra"),       # không được loại nhầm
            node(1, "Tai nghe bluetooth chống ồn", sales=9000),      # trùng
        ]
        ok, skipped = deals.rank(nodes)
        self.assertEqual([r["url"][-1] for r in ok], ["1", "6", "2"])
        reasons = {r["name"]: r["reason"] for r in skipped}
        self.assertIn("nhóm cấm", reasons["Viên uống giảm cân thảo mộc"])
        self.assertIn("đánh giá", reasons["Bàn phím cơ"])
        self.assertIn("mới bán", reasons["Chuột không dây"])
        self.assertEqual(ok[0]["commission_est"], "16.000đ")

    def test_add_to_queue_skips_existing(self):
        ok, _ = deals.rank([node(7, "Đèn bàn LED")])
        self.assertEqual(len(deals.add_to_queue(ok, "den ban")), 1)
        ok2, skipped = deals.rank([node(7, "Đèn bàn LED")])
        self.assertEqual(ok2, [])
        self.assertEqual(skipped[0]["reason"], "đã có trong hàng đợi")

    def test_search_builds_query(self):
        with mock.patch.object(deals.shopee, "_call", return_value={"productOfferV2": {"nodes": []}}) as call:
            deals.search('tai nghe "pro"', sort="hoa-hong")
            q = call.call_args[0][0]
        self.assertIn('keyword: "tai nghe \\"pro\\""', q)
        self.assertIn("sortType: 5", q)


class MotionPlanTest(unittest.TestCase):
    product = {"features": ["Giữ lạnh 24 giờ (theo mô tả shop)", "Inox 2 lớp", "Nắp chống tràn"]}

    def test_default_plan(self):
        lines = ["a", "b", "c", "d", "e", "f"]
        plan = motion.plan_scenes(lines, {"hook": "Móc"}, self.product, "89.000đ", "facebook")
        self.assertEqual([p["template"] for p in plan], ["hook", "product", "features", "product", "price", "outro"])
        self.assertEqual(plan[0]["headline"], "Móc")
        self.assertEqual(plan[-1]["cta"], "Link ở bình luận ghim")

    def test_visuals_override_and_validation(self):
        lines = ["a", "b"]
        plan = motion.plan_scenes(lines, {"visuals": [None, {"template": "callout", "statement": "X"}]},
                                  self.product, None, "tiktok")
        self.assertEqual(plan[1], {"template": "callout", "statement": "X"})
        with self.assertRaises(motion.MotionError):
            motion.plan_scenes(lines, {"visuals": [None]}, self.product, None, "tiktok")
        with self.assertRaises(motion.MotionError):
            motion.plan_scenes(lines, {"visuals": [None, {"template": "abc"}]}, self.product, None, "tiktok")

    def test_html_is_escaped(self):
        plan = motion.plan_scenes(["<b>x</b>"], {"hook": "<script>"}, self.product, None, "tiktok")
        out = motion.compose(["<b>x</b>"], [2.0], plan, ["img_00.jpg"], {"handle": "@a"}, None)
        self.assertNotIn("<script>alert", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn('data-start="0.000" data-duration="2.000"', out)


if __name__ == "__main__":
    unittest.main()
