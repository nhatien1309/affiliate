"""Chạy: python -m unittest discover tests
Chọn giọng đọc: lựa chọn trên giao diện (brand.json) ghi đè .env; thử lại khi dịch vụ lỗi tạm thời. Không gọi mạng."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import config, tts


class VoiceSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.brand = Path(self.tmp.name) / "brand.json"
        self.patches = [mock.patch.object(config, "BRAND_FILE", self.brand),
                        mock.patch.dict(os.environ, {"TTS_PROVIDER": "edge", "EDGE_VOICE": "vi-VN-HoaiMyNeural",
                                                     "EDGE_RATE": "+8%", "FPT_VOICE": "banmai"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_env_is_default_and_brand_overrides(self):
        vs = tts.voice_settings()
        self.assertEqual((vs["provider"], vs["edge_voice"], vs["edge_rate"]), ("edge", "vi-VN-HoaiMyNeural", "+8%"))
        self.assertEqual(tts.describe(vs), "Edge · Hoài My · nữ · +8%")
        self.brand.write_text(json.dumps({"voice": {"provider": "fpt", "fpt_voice": "leminh"}}), encoding="utf-8")
        vs = tts.voice_settings()
        self.assertEqual((vs["provider"], vs["fpt_voice"], vs["edge_rate"]), ("fpt", "leminh", "+8%"))
        self.assertEqual(tts.describe(vs), "FPT.AI · Lê Minh · nam Bắc")
        self.assertEqual(tts.describe(vs, "silent"), "Không tiếng")

    def test_synthesize_uses_override_and_retries(self):
        calls = []

        def flaky(text, dest, vs):
            calls.append(vs["edge_voice"])
            if len(calls) < 3:
                raise RuntimeError("NoAudioReceived")
            Path(dest).write_bytes(b"x")

        with mock.patch.dict(tts.PROVIDERS, {"edge": flaky}), mock.patch.object(tts, "duration", return_value=2.0), \
                mock.patch.object(tts.time, "sleep"):
            sec = tts.synthesize("Xin chào", Path(self.tmp.name) / "a.wav", voice={"edge_voice": "vi-VN-NamMinhNeural"})
        self.assertEqual((sec, calls), (2.0, ["vi-VN-NamMinhNeural"] * 3))

    def test_config_errors_are_not_retried(self):
        def missing_key(text, dest, vs):
            raise tts.TTSError("Thiếu FPT_API_KEY trong .env")

        with mock.patch.dict(tts.PROVIDERS, {"fpt": missing_key}) as _, mock.patch.object(tts.time, "sleep") as sleep:
            with self.assertRaises(tts.TTSError):
                tts.synthesize("Xin chào", Path(self.tmp.name) / "a.wav", provider="fpt")
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
