"""Tạo giọng đọc cho từng câu. Nhà cung cấp và giọng chọn trên giao diện điều khiển (lưu ở mục `voice`
trong brand/brand.json); chưa chọn thì dùng TTS_PROVIDER, EDGE_VOICE... trong .env:

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

from .config import brand, env

EDGE_VOICES = [  # (mã, tên hiện trên giao diện, nhóm)
    ("vi-VN-HoaiMyNeural", "Hoài My · nữ", "vi"),
    ("vi-VN-NamMinhNeural", "Nam Minh · nam", "vi"),
    *[(f"{loc}-{name}MultilingualNeural", f"{name} · {gender}", "ngoai")
      for loc, name, gender in [
          ("en-US", "Andrew", "nam"), ("en-US", "Brian", "nam"), ("en-AU", "William", "nam"),
          ("fr-FR", "Remy", "nam"), ("de-DE", "Florian", "nam"), ("it-IT", "Giuseppe", "nam"),
          ("ko-KR", "Hyunsu", "nam"), ("en-US", "Ava", "nữ"), ("en-US", "Emma", "nữ"),
          ("fr-FR", "Vivienne", "nữ"), ("de-DE", "Seraphina", "nữ"), ("pt-BR", "Thalita", "nữ")]],
]
FPT_VOICES = [
    ("banmai", "Ban Mai · nữ Bắc"), ("thuminh", "Thu Minh · nữ Bắc"), ("leminh", "Lê Minh · nam Bắc"),
    ("myan", "Mỹ An · nữ Trung"), ("ngoclam", "Ngọc Lam · nữ Trung"), ("giahuy", "Gia Huy · nam Trung"),
    ("lannhi", "Lan Nhi · nữ Nam"), ("linhsan", "Linh San · nữ Nam"), ("minhquang", "Minh Quang · nam Nam"),
]


def voice_settings() -> dict:
    """Giọng đang dùng: lựa chọn trên giao diện (brand.json → voice) ghi đè giá trị trong .env."""
    chosen = brand().get("voice") or {}
    return {
        "provider": chosen.get("provider") or env("TTS_PROVIDER", "edge"),
        "edge_voice": chosen.get("edge_voice") or env("EDGE_VOICE", "vi-VN-HoaiMyNeural"),
        "edge_rate": chosen.get("edge_rate") or env("EDGE_RATE", "+8%"),
        "edge_pitch": chosen.get("edge_pitch") or env("EDGE_PITCH", "+0Hz"),
        "elevenlabs_voice_id": chosen.get("elevenlabs_voice_id") or env("ELEVENLABS_VOICE_ID"),
        "elevenlabs_voice_name": chosen.get("elevenlabs_voice_name") or "",
        "fpt_voice": chosen.get("fpt_voice") or env("FPT_VOICE", "banmai"),
    }


def describe(vs: dict, provider: str | None = None) -> str:
    """Tên giọng dễ đọc cho giao diện và meta.json, vd "Edge · Hoài My · nữ · +8%"."""
    provider = provider or vs["provider"]
    if provider == "edge":
        name = {c: n for c, n, _ in EDGE_VOICES}.get(vs["edge_voice"], vs["edge_voice"])
        extra = [x for x in (vs["edge_rate"], vs["edge_pitch"]) if x not in ("+0%", "+0Hz")]
        return " · ".join(["Edge", name, *extra])
    if provider == "elevenlabs":
        return f"ElevenLabs · {vs['elevenlabs_voice_name'] or vs['elevenlabs_voice_id'] or 'chưa chọn giọng'}"
    if provider == "fpt":
        return f"FPT.AI · {dict(FPT_VOICES).get(vs['fpt_voice'], vs['fpt_voice'])}"
    return "Không tiếng"


def elevenlabs_voices() -> list[dict]:
    """Các giọng trong tài khoản ElevenLabs (khóa cần quyền Voices: Read). Không trả khóa ra ngoài."""
    key = env("ELEVENLABS_API_KEY")
    if not key:
        raise TTSError("Chưa có ELEVENLABS_API_KEY trong .env")
    r = requests.get("https://api.elevenlabs.io/v2/voices", headers={"xi-api-key": key},
                     params={"page_size": 100}, timeout=20)
    if r.status_code != 200:
        try:
            detail = r.json()["detail"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:200]
        raise TTSError(f"ElevenLabs lỗi {r.status_code}: {detail}")
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append({"id": v["voice_id"], "name": v.get("name", ""), "vi": labels.get("language") == "vi",
                    "premade": v.get("category") == "premade",  # gói Free chỉ gọi được loại này qua API
                    "gender": labels.get("gender", ""), "accent": labels.get("accent", "")})
    return out


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


def _silent(text: str, dest: Path, vs: dict) -> None:
    seconds = max(1.2, len(text) / 15)  # ~15 ký tự/giây, gần tốc độ đọc tiếng Việt
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", f"{seconds:.2f}", str(dest)],
        check=True,
    )


def _edge(text: str, dest: Path, vs: dict) -> None:
    try:
        import edge_tts
    except ImportError as e:
        raise TTSError("Chưa cài edge-tts: pip install edge-tts") from e
    mp3 = dest.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, vs["edge_voice"], rate=vs["edge_rate"], pitch=vs["edge_pitch"])
                .save(str(mp3)))
    _to_wav(mp3, dest)
    mp3.unlink(missing_ok=True)


def _elevenlabs(text: str, dest: Path, vs: dict) -> None:
    key, voice = env("ELEVENLABS_API_KEY"), vs["elevenlabs_voice_id"]
    if not key or not voice:
        raise TTSError("Thiếu ELEVENLABS_API_KEY trong .env hoặc chưa chọn giọng ElevenLabs trên giao diện")
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
        try:
            detail = r.json()["detail"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = r.text[:300]
        if r.status_code == 429 or r.status_code >= 500:
            raise RuntimeError(f"ElevenLabs lỗi {r.status_code}: {detail}")  # tạm thời: synthesize thử lại
        raise TTSError(f"ElevenLabs lỗi {r.status_code}: {detail}")
    mp3 = dest.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    _to_wav(mp3, dest)
    mp3.unlink(missing_ok=True)


def _fpt(text: str, dest: Path, vs: dict) -> None:
    key = env("FPT_API_KEY")
    if not key:
        raise TTSError("Thiếu FPT_API_KEY trong .env")
    r = requests.post(
        "https://api.fpt.ai/hmi/tts/v5",
        data=text.encode("utf-8"),
        headers={"api-key": key, "voice": vs["fpt_voice"], "speed": env("FPT_SPEED", "0")},
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
RETRY_DELAYS = (1, 2, 4)  # giây chờ trước mỗi lần thử lại; Edge thỉnh thoảng trả về rỗng (NoAudioReceived)


def synthesize(text: str, dest: Path, provider: str | None = None, voice: dict | None = None) -> float:
    """Ghi file WAV cho một câu và trả về độ dài (giây). Lỗi mạng/dịch vụ thì thử lại tối đa 3 lần.

    `voice` ghi đè vài mục của giọng đang chọn (giao diện dùng để nghe thử trước khi lưu)."""
    vs = {**voice_settings(), **(voice or {})}
    provider = provider or vs["provider"]
    if provider not in PROVIDERS:
        raise TTSError(f"TTS_PROVIDER không hợp lệ: {provider}. Dùng: {', '.join(PROVIDERS)}")
    for delay in (*RETRY_DELAYS, None):
        try:
            PROVIDERS[provider](text, dest, vs)
            break
        except TTSError:
            raise  # thiếu khóa, sai cấu hình: thử lại cũng vô ích
        except Exception:
            if delay is None:
                raise
            time.sleep(delay)
    return duration(dest)
