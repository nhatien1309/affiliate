"""Dựng video dọc 1080x1920 từ product.json + script_<nền tảng>.json.

Mỗi câu thoại là một cảnh: ảnh sản phẩm (nền mờ + ảnh chính), giá, phụ đề câu đó,
chuyển động zoom nhẹ. Các cảnh được nối lại, ghép giọng đọc và nhạc nền (nếu có).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import tts
from .config import MUSIC_DIR, OUTPUT_DIR, brand, font
from .product import load as load_product, workdir

W, H, FPS = 1080, 1920, 30
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SECONDS = {"facebook": 40, "tiktok": 30}  # khớp mục "Kịch bản" trong CLAUDE.md


class RenderError(RuntimeError):
    pass


# ---------- vẽ chữ ----------

def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _balance(draw, lines, fnt, max_w):
    """Chia lại để các dòng dài gần bằng nhau (tránh một chữ lẻ loi ở dòng cuối)."""
    if len(lines) < 2:
        return lines
    words = " ".join(lines).split()
    n = len(lines)
    best, lo, hi = lines, 1, max_w
    while lo <= hi:  # tìm bề rộng nhỏ nhất vẫn giữ nguyên số dòng
        mid = (lo + hi) // 2
        trial = _wrap(draw, " ".join(words), fnt, mid)
        if len(trial) <= n and all(draw.textlength(l, font=fnt) <= mid for l in trial):
            best, hi = trial, mid - 1
        else:
            lo = mid + 1
    return best


def _fit_text(draw, text, weight, size, max_w, max_lines, min_size=34):
    while size >= min_size:
        fnt = ImageFont.truetype(font(weight), size)
        lines = _wrap(draw, text, fnt, max_w)
        if len(lines) <= max_lines:
            return fnt, _balance(draw, lines, fnt, max_w)
        size -= 4
    fnt = ImageFont.truetype(font(weight), min_size)
    return fnt, _wrap(draw, text, fnt, max_w)[:max_lines]


def _draw_block(img, text, *, top=None, center_y=None, weight="Bold", size=60, max_w=960,
                max_lines=3, fill="#FFFFFF", stroke="#000000", stroke_w=6, line_gap=1.18):
    draw = ImageDraw.Draw(img)
    fnt, lines = _fit_text(draw, text, weight, size, max_w, max_lines)
    lh = int(fnt.size * line_gap)
    block_h = lh * len(lines)
    y = top if top is not None else int(center_y - block_h / 2)
    for line in lines:
        x = (W - draw.textlength(line, font=fnt)) / 2
        draw.text((x, y), line, font=fnt, fill=fill, stroke_width=stroke_w, stroke_fill=stroke)
        y += lh


# ---------- khung cảnh ----------

def _cover(img: Image.Image, size) -> Image.Image:
    return ImageOps.fit(img, size, method=Image.LANCZOS)


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0], img.size[1]], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def compose_base(image_path: Path, b: dict, price_text: str | None, hook: str | None) -> Image.Image:
    src = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")  # ảnh điện thoại: xoay đúng chiều
    bg = _cover(src, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), "#000000"), 0.45)

    fg = src.copy()
    fg.thumbnail((900, 800), Image.LANCZOS)
    fg = _rounded(fg, 36)
    shadow = Image.new("RGBA", (fg.width + 60, fg.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([30, 40, fg.width + 30, fg.height + 40], 40, fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    cx, cy = W // 2, 860
    bg.paste(shadow, (cx - shadow.width // 2, cy - shadow.height // 2), shadow)
    bg.paste(fg, (cx - fg.width // 2, cy - fg.height // 2), fg)

    if hook:
        _draw_block(bg, hook, top=190, weight="ExtraBold", size=80, max_w=980, max_lines=2, stroke_w=7)
    else:
        _draw_block(bg, b["handle"], center_y=380, weight="Bold", size=36, max_lines=1,
                    fill="#FFFFFF", stroke="#000000", stroke_w=3)

    if price_text:
        draw = ImageDraw.Draw(bg)
        fnt = ImageFont.truetype(font("ExtraBold"), 64)
        tw = draw.textlength(price_text, font=fnt)
        pw, ph, py = int(tw + 80), 104, 1352
        x0 = (W - pw) // 2
        draw.rounded_rectangle([x0, py - ph // 2, x0 + pw, py + ph // 2], ph // 2, fill=b["price_bg"])
        draw.text((W / 2, py), price_text, font=fnt, fill=b["price_text"], anchor="mm")
    return bg


def caption_png(text: str, b: dict) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _draw_block(img, text, center_y=1535, weight="Bold", size=60, max_w=960, max_lines=3,
                fill=b["caption_color"], stroke=b["caption_stroke"], stroke_w=6)
    return img


# ---------- ffmpeg ----------

def _run(args: list[str]) -> None:
    res = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RenderError(res.stderr[-1500:])


def _segment(base: Path, cap: Path, dur: float, zoom_in: bool, out: Path) -> None:
    z = 0.06
    f = f"(1+{z}*t/{dur:.3f})" if zoom_in else f"(1+{z}*(1-t/{dur:.3f}))"
    vf = (
        f"[0:v]scale=w='trunc({W}*{f}/2)*2':h='trunc({H}*{f}/2)*2':eval=frame,"
        f"crop={W}:{H},setsar=1[b];[b][1:v]overlay=0:0,format=yuv420p[v]"
    )
    _run([
        "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(base),
        "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(cap),
        "-filter_complex", vf, "-map", "[v]", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out),
    ])


def _concat(files: list[Path], out: Path, copy: bool = True) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in files), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", str(lst), *(["-c", "copy"] if copy else []), str(out)])


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _pick_music(b: dict) -> Path | None:
    if b.get("music"):
        p = MUSIC_DIR / b["music"]
        return p if p.exists() else None
    tracks = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in {".mp3", ".m4a", ".wav"})
    return tracks[0] if tracks else None


# ---------- chính ----------

def render(slug: str, platform: str, provider: str | None = None) -> Path:
    folder = workdir(slug)
    product = load_product(slug)
    script_path = folder / f"script_{platform}.json"
    if not script_path.exists():
        raise RenderError(f"Chưa có {script_path.name}. Agent cần viết kịch bản trước.")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    lines = [l.strip() for l in script.get("lines", []) if l.strip()]
    if not lines:
        raise RenderError("Kịch bản không có câu thoại nào (trường 'lines').")

    images = sorted(p for p in (folder / "images").glob("*") if p.suffix.lower() in IMAGE_EXT)
    if not images:
        raise RenderError(f"Chưa có ảnh trong {folder / 'images'}")

    b = brand()
    price = script.get("price_text") or product.get("price_text")
    tmp = folder / f"_build_{platform}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    segs, pads, srt, t = [], [], [], 0.0
    base_cache: dict[tuple, Path] = {}
    for i, line in enumerate(lines):
        wav = tmp / f"voice_{i:02}.wav"
        spoken = tts.synthesize(line, wav, provider)
        dur = spoken + (0.8 if i == len(lines) - 1 else 0.25)

        padded = tmp / f"voicepad_{i:02}.wav"
        _run(["-i", str(wav), "-af", f"apad=whole_dur={dur:.3f}", "-t", f"{dur:.3f}", "-ar", "44100", "-ac", "1", str(padded)])
        pads.append(padded)

        img = images[i % len(images)]
        hook = script.get("hook") if i == 0 else None
        key = (img, hook)
        if key not in base_cache:
            p = tmp / f"base_{len(base_cache):02}.png"
            compose_base(img, b, price, hook).save(p)
            base_cache[key] = p
        cap = tmp / f"cap_{i:02}.png"
        caption_png(line, b).save(cap)

        seg = tmp / f"seg_{i:02}.mp4"
        _segment(base_cache[key], cap, dur, zoom_in=(i % 2 == 0), out=seg)
        segs.append(seg)
        srt.append(f"{i + 1}\n{_srt_time(t)} --> {_srt_time(t + spoken)}\n{line}\n")
        t += dur

    video = tmp / "video.mp4"
    voice = tmp / "voice.wav"
    _concat(segs, video)
    _concat(pads, voice)

    out_dir = OUTPUT_DIR / slug / platform
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "video.mp4"
    music = _pick_music(b)
    if music:
        vol = float(b.get("music_volume", 0.12))
        fade_start = max(0.0, t - 1.5)
        _run([
            "-i", str(video), "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex",
            f"[2:a]volume={vol},afade=t=out:st={fade_start:.2f}:d=1.5[m];"
            f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-t", f"{t:.3f}", "-movflags", "+faststart", str(final),
        ])
    else:
        _run(["-i", str(video), "-i", str(voice), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(final)])

    # ảnh bìa = cảnh đầu có câu móc
    first_base = base_cache[(images[0], script.get("hook"))]
    Image.open(first_base).convert("RGB").save(out_dir / "cover.jpg", quality=90)
    (out_dir / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")

    tags = " ".join(script.get("hashtags", []))
    caption = [script.get("caption", "").strip(), tags, b["disclosure"]]
    if platform == "facebook" and product.get("affiliate_link"):
        caption.append("\n--- BÌNH LUẬN ĐẦU (ghim) ---\n" + script.get("comment", "Link mua: {link}").replace(
            "{link}", product["affiliate_link"]))
    (out_dir / "caption.txt").write_text("\n\n".join(c for c in caption if c), encoding="utf-8")

    warnings = []
    limit = MAX_SECONDS[platform]
    if t > limit:
        warnings.append(f"Video dài {t:.0f}s, vượt {limit}s khuyến nghị cho {platform}. Rút gọn kịch bản.")

    meta = {"slug": slug, "platform": platform, "seconds": round(t, 1), "scenes": len(lines),
            "music": music.name if music else None, "tts": provider or "mặc định trong .env",
            "warnings": warnings}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)

    for w in warnings:
        print(f"CẢNH BÁO: {w}")
    return final
