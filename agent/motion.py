"""Engine dựng video motion graphics bằng HyperFrames (HTML + CSS + GSAP -> MP4).

Chuyển thể từ auto-video-gen của Cuongyd196 (giấy phép MIT, xem agent/motion_templates/NOTICE.md),
viết lại bằng Python và đổi từ video tin tức sang video sản phẩm affiliate.

Mỗi câu thoại là một cảnh. Kiểu cảnh (template) lấy từ `visuals` trong kịch bản nếu có,
không thì tự chọn:  câu đầu = hook, câu cuối = outro, ở giữa = product / features / price.

  hook      ảnh sản phẩm + câu móc chữ to
  product   ảnh sản phẩm zoom chậm + giá
  features  thẻ "điểm nổi bật" (lấy từ product.json -> features)
  price     giá chữ to, có thể kèm giá cũ gạch ngang và % giảm
  callout   một câu nhấn mạnh trong thẻ
  outro     lời kêu gọi (link ở bình luận ghim / bio / giỏ hàng) + tên kênh

Chỉ tạo hình, không có tiếng: render.py ghép giọng đọc và nhạc nền sau.
Cần Node.js (có sẵn npx). Lần đầu chạy, npx tự tải HyperFrames và trình duyệt Chrome để dựng.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from .config import FONTS_DIR, env

TEMPLATE_DIR = Path(__file__).resolve().parent / "motion_templates"
TEMPLATES = ("hook", "product", "features", "price", "callout", "outro")
W, H, FPS = 1080, 1920, 30
DEFAULT_VERSION = "0.8.82"  # đã chạy thử với bản này; đổi bằng HYPERFRAMES_VERSION trong .env


class MotionError(RuntimeError):
    pass


def _e(text) -> str:
    return html.escape(str(text or ""), quote=True)


# ---------- chọn kiểu cảnh ----------

def default_cta(platform: str) -> str:
    if platform == "facebook":
        return "Link ở bình luận ghim"
    return "Bấm giỏ hàng bên dưới" if env("TIKTOK_HAS_CART", "false").lower() == "true" else "Link ở bio"


def plan_scenes(lines: list[str], script: dict, product: dict, price_text: str | None, platform: str) -> list[dict]:
    """Trả về danh sách cảnh [{template, ...}] cùng độ dài với lines."""
    visuals = script.get("visuals") or []
    if visuals and len(visuals) != len(lines):
        raise MotionError(f"'visuals' có {len(visuals)} phần tử nhưng 'lines' có {len(lines)}. Hai mảng phải dài bằng nhau.")
    features = [f for f in product.get("features", []) if f]
    n = len(lines)
    plan: list[dict] = []
    used_features = used_price = False
    for i in range(n):
        if visuals and visuals[i]:
            v = dict(visuals[i])
            if v.get("template") not in TEMPLATES:
                raise MotionError(f"visuals[{i}].template phải là một trong: {', '.join(TEMPLATES)}")
        elif i == 0:
            v = {"template": "hook"}
        elif i == n - 1 and n > 1:
            v = {"template": "outro"}
        else:
            k, middle = i - 1, n - 2
            if k == 1 and len(features) >= 2 and not used_features:
                v = {"template": "features"}
            elif k == middle - 1 and middle >= 2 and price_text and not used_price:
                v = {"template": "price"}
            else:
                v = {"template": "product"}
        used_features |= v["template"] == "features"
        used_price |= v["template"] == "price"
        # điền giá trị mặc định
        t = v["template"]
        if t == "hook":
            v.setdefault("headline", script.get("hook") or lines[0])
        elif t == "features":
            v.setdefault("title", "Điểm nổi bật")
            v.setdefault("bullets", features[:4])
            if not v["bullets"]:
                v = {"template": "product"}
        elif t == "price":
            v.setdefault("value", price_text or "")
            v.setdefault("old", product.get("price_before_text"))
            v.setdefault("badge", f"-{product['discount_rate']}%" if product.get("discount_rate") else None)
            v.setdefault("note", "Giá có thể đổi theo thời điểm")
            if not v["value"]:
                v = {"template": "product"}
        elif t == "callout":
            v.setdefault("statement", lines[i])
        elif t == "outro":
            v.setdefault("cta", default_cta(platform))
        plan.append(v)
    return plan


# ---------- HTML ----------

def _subtitle(text: str) -> str:
    words = text.split()
    spans = "".join(f'<span class="w">{_e(w)}</span> ' for w in words)
    return f'<div class="sub"><div class="sub-inner">{spans}</div></div>'


def _price_pill(price_text: str | None) -> str:
    return f'<div class="price-pill">{_e(price_text)}</div>' if price_text else ""


def _scene_html(i: int, v: dict, line: str, img: str, price_text: str | None, brand: dict) -> str:
    t = v["template"]
    if t == "hook":
        inner = f'''
  <div class="bg-photo" style="background-image:url('{img}')"></div>
  <div class="bg-dim"></div>
  <div class="hook-headline">{_e(v["headline"])}</div>
  <div class="card kb"><img src="{img}" alt=""></div>
  {_price_pill(price_text)}'''
    elif t == "product":
        inner = f'''
  <div class="card card-lg kb"><img src="{img}" alt=""></div>
  {_price_pill(price_text)}'''
    elif t == "features":
        bullets = "".join(
            f'<div class="feat"><div class="feat-dot">✓</div><div class="feat-text">{_e(b)}</div></div>'
            for b in v["bullets"][:4])
        inner = f'''
  <div class="thumb"><img src="{img}" alt=""></div>
  <div class="feat-card">
    <div class="feat-title">{_e(v["title"])}</div>
    <div class="feat-rule"></div>
    {bullets}
  </div>'''
    elif t == "price":
        old = f'<div class="price-old">{_e(v["old"])}</div>' if v.get("old") else ""
        badge = f'<div class="price-badge">{_e(v["badge"])}</div>' if v.get("badge") else ""
        note = f'<div class="price-note">{_e(v["note"])}</div>' if v.get("note") else ""
        inner = f'''
  <div class="thumb thumb-lg"><img src="{img}" alt=""></div>
  <div class="price-block">
    {old}
    <div class="price-big shine">{_e(v["value"])}</div>
    {badge}
    {note}
  </div>'''
    elif t == "callout":
        tag = f'<div class="callout-tag">{_e(v["tag"])}</div>' if v.get("tag") else ""
        inner = f'''
  <div class="thumb"><img src="{img}" alt=""></div>
  <div class="callout-card">{tag}<div class="callout-text">{_e(v["statement"])}</div></div>'''
    else:  # outro
        inner = f'''
  <div class="thumb"><img src="{img}" alt=""></div>
  <div class="outro">
    <div class="outro-cta">{_e(v["cta"])}</div>
    <div class="outro-arrow">↓</div>
    <div class="follow-card">
      <div class="follow-avatar">{_e((brand.get("handle") or "@").lstrip("@")[:1].upper())}</div>
      <div class="follow-name">{_e(brand.get("handle"))}</div>
      <div class="follow-btn"><span class="fb-follow">Theo dõi</span><span class="fb-done">Đã theo dõi ✓</span></div>
    </div>
  </div>'''
    return (f'<div class="scene clip" id="s{i}" data-layout="{t}">{inner}\n  {_subtitle(line)}\n</div>')


def _css_vars(brand: dict) -> str:
    return (":root{"
            f"--accent:{brand.get('accent', '#0F766E')};"
            f"--accent-text:{brand.get('accent_text', '#FFFFFF')};"
            f"--price-bg:{brand.get('price_bg', '#FFD23F')};"
            f"--price-text:{brand.get('price_text', '#16201E')};"
            f"--sub-color:{brand.get('caption_color', '#FFFFFF')};"
            f"--sub-stroke:{brand.get('caption_stroke', '#000000')};"
            "}")


def compose(lines, durations, plan, image_names, brand, price_text) -> str:
    starts, t = [], 0.0
    for d in durations:
        starts.append(t)
        t += d
    total = t
    scenes = []
    for i, (line, v) in enumerate(zip(lines, plan)):
        html_i = _scene_html(i, v, line, image_names[i % len(image_names)], price_text, brand)
        # gắn mốc thời gian cho HyperFrames
        html_i = html_i.replace(f'id="s{i}"',
                                f'id="s{i}" data-start="{starts[i]:.3f}" data-duration="{durations[i]:.3f}"', 1)
        scenes.append(html_i)
    tag = brand.get("video_tag", "Tiếp thị liên kết")
    tpl = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    return (tpl
            .replace("{{CSS_VARS}}", _css_vars(brand))
            .replace("{{TOTAL}}", f"{total:.3f}")
            .replace("{{HANDLE}}", _e(brand.get("handle", "")))
            .replace("{{TAG}}", _e(tag))
            .replace("{{SCENES}}", "\n".join(scenes)))


# ---------- dựng ----------

def _prepare_images(images: list[Path], dest: Path) -> list[str]:
    names = []
    for k, src in enumerate(images):
        name = f"img_{k:02}.jpg"
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")  # ảnh điện thoại: xoay đúng chiều
        im.thumbnail((1400, 1400), Image.LANCZOS)
        im.save(dest / name, quality=92)
        names.append(name)
    return names


def _npx() -> str:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise MotionError("Engine hyperframes cần Node.js (lệnh npx). Cài Node.js LTS (xem README) "
                          "hoặc dùng --engine ffmpeg.")
    return exe


def render_video(*, product: dict, script: dict, lines: list[str], durations: list[float], images: list[Path],
                 brand: dict, price_text: str | None, platform: str, build_dir: Path, out: Path) -> Path:
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)
    for f in ("styles.css", "gsap.min.js", "animations.js"):
        shutil.copy(TEMPLATE_DIR / f, build_dir / f)
    for f in FONTS_DIR.glob("BeVietnamPro-*.ttf"):
        shutil.copy(f, build_dir / f.name)

    plan = plan_scenes(lines, script, product, price_text, platform)
    names = _prepare_images(images, build_dir)
    (build_dir / "index.html").write_text(compose(lines, durations, plan, names, brand, price_text), encoding="utf-8")
    (build_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    version = env("HYPERFRAMES_VERSION", DEFAULT_VERSION)
    quality = env("HYPERFRAMES_QUALITY", "standard")
    cmd = [_npx(), "-y", f"hyperframes@{version}", "render", str(build_dir),
           "-o", str(out), "-f", str(FPS), "-q", quality, "--quiet"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if res.returncode != 0 or not out.exists():
        tail = re.sub(r"\x1b\[[0-9;]*m", "", (res.stderr or "") + (res.stdout or ""))[-1500:]
        hint = ""
        if "Download failed" in tail or "browser ensure" in tail:
            hint = "\nGợi ý: chạy `npx hyperframes browser ensure` một lần để tải Chrome dùng cho việc dựng."
        raise MotionError(f"HyperFrames dựng thất bại (mã {res.returncode}):\n{tail}{hint}")
    return out
