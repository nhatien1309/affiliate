"""Tạo giọng đọc cho từng câu. Nhà cung cấp chọn bằng TTS_PROVIDER trong .env:

- edge        : miễn phí (dịch vụ không chính thức của Microsoft Edge) — hợp để thử
- elevenlabs  : chất lượng cao, trả phí
- fpt         : FPT.AI, giọng Việt nhiều vùng miền, trả phí
- silent      : không có tiếng, chỉ để chạy thử bố cục
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import requests

from .config import env


class TTSError(RuntimeError):
    pass


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _to_wav(src: Path, dest: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", "44100", "-ac", "1", str(dest)],
        check=True,
    )


def _silent(text: str, dest: Path) -> None:
    seconds = max(1.2, len(text) / 15)  # ~15 ký tự/giây, gần tốc độ đọc tiếng Việt
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", f"{seconds:.2f}", str(dest)],
        check=True,
    )


def _edge(text: str, dest: Path) -> None:
    try:
        import edge_tts
    except ImportError as e:
        raise TTSError("Chưa cài edge-tts: pip install edge-tts") from e
    voice = env("EDGE_VOICE", "vi-VN-HoaiMyNeural")
    rate = env("EDGE_RATE", "+8%")
    mp3 = dest.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(mp3)))
    _to_wav(mp3, dest)
    mp3.unlink(missing_ok=True)


def _elevenlabs(text: str, dest: Path) -> None:
    key, voice = env("ELEVENLABS_API_KEY"), env("ELEVENLABS_VOICE_ID")
    if not key or not voice:
        raise TTSError("Thiếu ELEVENLABS_API_KEY hoặc ELEVENLABS_VOICE_ID trong .env")
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": env("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
            "language_code": "vi",
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.2},
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise TTSError(f"ElevenLabs lỗi {r.status_code}: {r.text[:300]}")
    mp3 = dest.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    _to_wav(mp3, dest)
    mp3.unlink(missing_ok=True)


def _fpt(text: str, dest: Path) -> None:
    key = env("FPT_API_KEY")
    if not key:
        raise TTSError("Thiếu FPT_API_KEY trong .env")
    r = requests.post(
        "https://api.fpt.ai/hmi/tts/v5",
        data=text.encode("utf-8"),
        headers={"api-key": key, "voice": env("FPT_VOICE", "banmai"), "speed": env("FPT_SPEED", "0")},
        timeout=30,
    )
    r.raise_for_status()
    link = r.json().get("async")
    if not link:
        raise TTSError(f"FPT.AI không trả link âm thanh: {r.text[:300]}")
    mp3 = dest.with_suffix(".mp3")
    for _ in range(30):  # FPT tạo file bất đồng bộ, chờ tối đa ~60 giây
        a = requests.get(link, timeout=30)
        if a.status_code == 200 and len(a.content) > 1000:
            mp3.write_bytes(a.content)
            break
        time.sleep(2)
    else:
        raise TTSError("FPT.AI chưa tạo xong file âm thanh sau 60 giây")
    _to_wav(mp3, dest)
    mp3.unlink(missing_ok=True)


PROVIDERS = {"edge": _edge, "elevenlabs": _elevenlabs, "fpt": _fpt, "silent": _silent}


def synthesize(text: str, dest: Path, provider: str | None = None) -> float:
    """Ghi file WAV cho một câu và trả về độ dài (giây)."""
    provider = provider or env("TTS_PROVIDER", "edge")
    if provider not in PROVIDERS:
        raise TTSError(f"TTS_PROVIDER không hợp lệ: {provider}. Dùng: {', '.join(PROVIDERS)}")
    PROVIDERS[provider](text, dest)
    return duration(dest)
