"""Chạy: python -m unittest discover tests
Giao diện điều khiển: hàng chờ lệnh, đọc luồng sự kiện Claude, chặn truy cập lạ. Không gọi Claude thật."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from agent import config, queue_store, ui


def wait(job, until=ui.DONE, timeout=20):
    end = time.time() + timeout
    while job.status not in until:
        if time.time() > end:
            raise AssertionError(f"lệnh vẫn ở trạng thái {job.status}")
        time.sleep(0.05)


class TempDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "work").mkdir()
        (root / "output").mkdir()
        self.patches = [
            mock.patch.object(queue_store, "QUEUE_FILE", root / "queue.csv"),
            mock.patch.object(config, "BRAND_FILE", root / "brand.json"),
            mock.patch.object(ui, "UI_LOG_DIR", root / "logs" / "ui"),
            mock.patch.object(ui, "WORK_DIR", root / "work"),
            mock.patch.object(ui, "OUTPUT_DIR", root / "output"),
        ]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class ClaudeEventTest(unittest.TestCase):
    def test_text_and_tool(self):
        lines, failed = ui.claude_event(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Đang làm"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "python -m agent doctor"}},
        ]}}))
        self.assertEqual(lines, [("text", "Đang làm"), ("tool", "▸ Bash: python -m agent doctor")])
        self.assertFalse(failed)

    def test_result_and_denials(self):
        lines, failed = ui.claude_event(json.dumps({
            "type": "result", "subtype": "success", "is_error": False, "duration_ms": 4200, "total_cost_usd": 0.05,
            "permission_denials": [{"tool_name": "PowerShell", "tool_input": {"command": "ls"}}]}))
        self.assertFalse(failed)
        self.assertEqual(lines[0], ("warn", "Bị chặn quyền: PowerShell ls"))
        self.assertEqual(lines[1], ("info", "Claude xong · 4 giây · ≈ $0.05"))
        _, failed = ui.claude_event(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True}))
        self.assertTrue(failed)

    def test_tool_error_and_plain_text(self):
        lines, _ = ui.claude_event(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": [{"type": "text", "text": "LỖI: thiếu ảnh"}]}]}}))
        self.assertEqual(lines, [("err", "✗ LỖI: thiếu ảnh")])
        self.assertEqual(ui.claude_event("﻿Ignoring 10 permissions"), ([("warn", "Ignoring 10 permissions")], False))
        self.assertEqual(ui.claude_event(""), ([], False))


class RunnerTest(TempDirs):
    def test_runs_in_order_and_captures_output(self):
        r = ui.Runner()
        a = r.submit("a", [sys.executable, "-c", "print('xin chào')"], "python")
        b = r.submit("b", [sys.executable, "-c", "import sys; print('LỖI: hỏng'); sys.exit(1)"], "python")
        wait(b)
        self.assertEqual(a.status, "xong")
        self.assertIn({"k": "out", "s": "xin chào"}, a.lines)
        self.assertEqual(b.status, "loi")
        self.assertIn({"k": "err", "s": "LỖI: hỏng"}, b.lines)
        self.assertLessEqual(a.ended, b.started)  # chạy lần lượt, không chồng nhau
        self.assertTrue(list((self.root / "logs" / "ui").glob("*.log")))

    def test_stop_running_and_waiting_jobs(self):
        r = ui.Runner()
        slow = r.submit("chậm", [sys.executable, "-c", "import time; time.sleep(30)"], "python")
        later = r.submit("sau", [sys.executable, "-c", "print(1)"], "python")
        wait(slow, ("dang_chay",))
        r.stop(later)
        self.assertEqual(later.status, "da_dung")
        r.stop(slow)
        wait(slow)
        self.assertEqual(slow.status, "da_dung")


class BuildJobTest(TempDirs):
    def test_render_validates_input(self):
        (self.root / "work" / "binh-nuoc").mkdir()
        title, cmd, kind = ui.build_job("render", {"slug": "binh-nuoc", "platform": "tiktok", "engine": "hyperframes"})
        self.assertEqual(kind, "python")
        self.assertEqual(cmd[4:], ["render", "binh-nuoc", "--platform", "tiktok", "--engine", "hyperframes"])
        self.assertEqual(title, "Dựng tiktok · binh-nuoc")
        for bad in ({"slug": "../x"}, {"slug": "khong-co"}, {"slug": "binh-nuoc", "engine": "rm -rf"}):
            with self.assertRaises(ValueError):
                ui.build_job("render", bad)
        with self.assertRaises(ValueError):
            ui.build_job("xoa-het", {})

    def test_claude_prompts(self):
        with mock.patch.object(ui.shutil, "which", return_value="claude"):
            _, cmd, kind = ui.build_job("lam-video", {"target": "a1b2c3"})
            self.assertEqual((kind, cmd[1:3]), ("claude", ["-p", "/lam-video a1b2c3"]))
            _, cmd, _ = ui.build_job("tim-deal", {"keyword": "tai nghe\n/xoa", "count": "99"})
            self.assertEqual(cmd[2], "/tim-deal từ khóa: tai nghe /xoa, số lượng: 20")
            with self.assertRaises(ValueError):
                ui.build_job("lam-video", {"target": "không phải link"})


class ServerTest(TempDirs):
    def setUp(self):
        super().setUp()
        self.httpd, self.token, self.runner = ui.make_server(0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, path, body=None, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = self.token
        if host:
            headers["Host"] = host
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_page_embeds_token(self):
        code, html = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(self.token, html)

    def test_post_needs_token_and_local_host(self):
        self.assertEqual(self.call("/api/queue/add", {"url": "https://shopee.vn/a-i.1.2"}, token=False)[0], 403)
        self.assertEqual(self.call("/api/state", host="evil.example")[0], 403)

    def test_add_link_then_state(self):
        code, _ = self.call("/api/queue/add", {"url": "https://shopee.vn/binh-i.1.2", "note": "thử"})
        self.assertEqual(code, 200)
        code, body = self.call("/api/state")
        state = json.loads(body)
        self.assertEqual([r["note"] for r in state["queue"]], ["thử"])
        self.assertNotIn("SHOPEE_SECRET", body)
        code, body = self.call("/api/queue/add", {"url": "https://shopee.vn/binh-i.1.2"})
        self.assertEqual(code, 400)
        self.assertIn("đã có trong hàng đợi", json.loads(body)["error"])

    def test_toggle_show_price(self):
        (self.root / "brand.json").write_text('{"handle": "@kenh"}', encoding="utf-8")
        self.assertFalse(json.loads(self.call("/api/state")[1])["settings"]["SHOW_PRICE"])  # mặc định tắt
        code, body = self.call("/api/settings", {"show_price": True})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["settings"]["SHOW_PRICE"])
        saved = json.loads((self.root / "brand.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, {"handle": "@kenh", "show_price": True})  # giữ nguyên các mục khác
        self.assertEqual(self.call("/api/settings", {"show_price": "yes"})[0], 400)
        self.assertEqual(self.call("/api/settings", {"show_price": False}, token=False)[0], 403)

    def test_choose_voice(self):
        (self.root / "brand.json").write_text('{"handle": "@kenh"}', encoding="utf-8")
        code, body = self.call("/api/voice", {"provider": "edge", "edge_voice": "vi-VN-NamMinhNeural",
                                              "edge_rate": "+15%", "edge_pitch": "-4Hz"})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["settings"]["VOICE_LABEL"], "Edge · Nam Minh · nam · +15% · -4Hz")
        code, _ = self.call("/api/voice", {"provider": "fpt", "fpt_voice": "leminh"})
        saved = json.loads((self.root / "brand.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["handle"], "@kenh")
        self.assertEqual(saved["voice"]["provider"], "fpt")
        self.assertEqual(saved["voice"]["edge_voice"], "vi-VN-NamMinhNeural")  # đổi nhà cung cấp vẫn nhớ giọng Edge
        for bad in ({"provider": "silent"}, {"provider": "edge", "edge_voice": "x"},
                    {"provider": "edge", "edge_voice": "vi-VN-HoaiMyNeural", "edge_rate": "nhanh"},
                    {"provider": "elevenlabs", "elevenlabs_voice_id": "../../x"}, {"provider": "fpt", "fpt_voice": "ai"}):
            self.assertEqual(self.call("/api/voice", bad)[0], 400, bad)
        self.assertEqual(self.call("/api/voice", {"provider": "fpt", "fpt_voice": "banmai"}, token=False)[0], 403)

    def test_voice_preview_is_cached(self):
        def fake(text, dest, provider=None, voice=None):
            Path(dest).write_bytes(b"RIFFwav")
            return 1.0

        body = {"provider": "edge", "edge_voice": "vi-VN-HoaiMyNeural", "edge_rate": "+8%", "edge_pitch": "+0Hz"}
        with mock.patch.object(ui.tts, "synthesize", side_effect=fake) as synth:
            code, first = self.call("/api/voice/preview", body)
            _, second = self.call("/api/voice/preview", body)
        self.assertEqual(code, 200)
        self.assertEqual(synth.call_count, 1)  # nghe lại không tạo (không tốn ký tự) lần nữa
        url = json.loads(first)["url"]
        self.assertEqual(url, json.loads(second)["url"])
        with urllib.request.urlopen(self.base + url, timeout=10) as r:
            self.assertEqual((r.headers["Content-Type"], r.read()), ("audio/wav", b"RIFFwav"))
        self.assertEqual(list((self.root / "output" / "_nghe-thu").glob("*.tmp.wav")), [])
        self.assertNotIn("_nghe-thu", [p["slug"] for p in json.loads(self.call("/api/state")[1])["products"]])
        with mock.patch.object(ui.tts, "synthesize", side_effect=ui.tts.TTSError("Thiếu FPT_API_KEY trong .env")):
            code, body = self.call("/api/voice/preview", {"provider": "fpt", "fpt_voice": "banmai"})
        self.assertEqual((code, json.loads(body)["error"]), (400, "Thiếu FPT_API_KEY trong .env"))

    def test_voice_lists_without_elevenlabs(self):
        ui._el_cache.update(at=0.0, voices=None, error=None)
        with mock.patch.object(ui.tts, "elevenlabs_voices", side_effect=ui.tts.TTSError("Chưa có ELEVENLABS_API_KEY")):
            code, body = self.call("/api/voices")
        data = json.loads(body)
        self.assertEqual(code, 200)
        self.assertIn({"id": "vi-VN-HoaiMyNeural", "name": "Hoài My · nữ", "group": "vi"}, data["edge"])
        self.assertEqual(len(data["fpt"]), 9)
        self.assertIsNone(data["elevenlabs"])
        self.assertEqual(data["elevenlabs_error"], "Chưa có ELEVENLABS_API_KEY")
        ui._el_cache.update(at=0.0)

    def test_media_blocks_path_traversal(self):
        out = self.root / "output" / "sp" / "facebook"
        out.mkdir(parents=True)
        (out / "video.mp4").write_bytes(b"0123456789")
        (self.root / "secret.txt").write_text("x")
        self.assertEqual(self.call("/media/output/sp/facebook/video.mp4")[0], 200)
        self.assertEqual(self.call("/media/output/..%2Fsecret.txt")[0], 404)
        self.assertEqual(self.call("/media/output/sp/..%2F..%2Fsecret.txt")[0], 404)

    def test_video_range(self):
        out = self.root / "output" / "sp" / "tiktok"
        out.mkdir(parents=True)
        (out / "video.mp4").write_bytes(b"0123456789")
        req = urllib.request.Request(self.base + "/media/output/sp/tiktok/video.mp4", headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual((r.status, r.read(), r.headers["Content-Range"]), (206, b"2345", "bytes 2-5/10"))


if __name__ == "__main__":
    unittest.main()
