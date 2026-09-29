"""Chạy: python -m unittest discover tests
Bật/tắt hiện giá trong video. Không dựng video thật."""
import unittest

from agent import motion, render


class PriceTest(unittest.TestCase):
    def test_price_mentions(self):
        lines = ["Giá chỉ 89 nghìn thôi", "Dung tích 750 ml", "Giữ lạnh 24 tiếng", "Chỉ 89.000đ",
                 "Rẻ 10k", "Nặng 10kg", "Xem chi tiết ở bình luận ghim"]
        self.assertEqual(render.price_mentions(lines), ["Giá chỉ 89 nghìn thôi", "Chỉ 89.000đ", "Rẻ 10k"])

    def test_without_price_scenes(self):
        script = {"hook": "Móc", "visuals": [None, {"template": "price", "value": "89.000đ"},
                                             {"template": "callout", "statement": "X"}, None, None]}
        out = render.without_price_scenes(script)
        self.assertEqual(out["visuals"], [None, None, {"template": "callout", "statement": "X"}, None, None])
        self.assertEqual(script["visuals"][1]["template"], "price")  # không sửa kịch bản gốc
        # khi tắt giá, render truyền price_text=None: motion không tự chọn cảnh giá
        plan = motion.plan_scenes(["a", "b", "c", "d", "e"], out, {"features": []}, None, "facebook")
        self.assertNotIn("price", [p["template"] for p in plan])


if __name__ == "__main__":
    unittest.main()
