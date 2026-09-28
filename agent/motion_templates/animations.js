// Chuyển động cho từng kiểu cảnh. HyperFrames tua timeline này theo từng khung hình.
// Chuyển thể từ auto-video-gen (MIT). Chỉ dùng các thuộc tính GSAP đơn giản:
// opacity, x, y, scale, scaleX. Không dùng `delay`, dùng tham số vị trí (đối số thứ 3).

window.__timelines = window.__timelines || {};
const tl = gsap.timeline({ paused: true });
window.__timelines["main"] = tl;

(function () {
  document.querySelectorAll(".shine").forEach((el) => {
    const m = document.createElement("div");
    m.className = "shine-mask";
    el.appendChild(m);
  });

  const scenes = Array.from(document.querySelectorAll("#stage .scene"));
  const q = (scene, sel) => scene.querySelector(sel);
  const qa = (scene, sel) => Array.from(scene.querySelectorAll(sel));

  scenes.forEach((scene, idx) => {
    const start = parseFloat(scene.dataset.start);
    const dur = parseFloat(scene.dataset.duration);
    const layout = scene.dataset.layout;

    tl.set(scene, { opacity: 1 }, start);
    if (idx < scenes.length - 1) tl.set(scene, { opacity: 0 }, start + dur);

    // ảnh zoom chậm (Ken Burns)
    qa(scene, ".kb img, .thumb img").forEach((img, k) => {
      const zoomIn = (idx + k) % 2 === 0;
      tl.fromTo(img, { scale: zoomIn ? 1 : 1.08 }, { scale: zoomIn ? 1.08 : 1, duration: dur, ease: "none" }, start);
    });
    const shine = (el, at) => {
      const m = el && el.querySelector(".shine-mask");
      if (!m) return;
      const travel = el.offsetWidth * 1.6;
      tl.set(m, { opacity: 1 }, at);
      tl.fromTo(m, { x: 0 }, { x: travel, duration: 0.9, ease: "none" }, at);
      tl.set(m, { opacity: 0 }, at + 0.9);
    };

    if (layout === "hook") {
      const h = q(scene, ".hook-headline");
      tl.fromTo(h, { scale: 0.55, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5 }, start + 0.05);
      tl.fromTo(q(scene, ".card"), { y: 120, opacity: 0 }, { y: 0, opacity: 1, duration: 0.5 }, start + 0.2);
    } else if (layout === "product") {
      tl.fromTo(q(scene, ".card"), { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45 }, start);
    } else if (layout === "features") {
      tl.fromTo(q(scene, ".thumb"), { scale: 0.7, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4 }, start);
      tl.fromTo(q(scene, ".feat-card"), { y: 80, opacity: 0 }, { y: 0, opacity: 1, duration: 0.45 }, start + 0.1);
      tl.fromTo(q(scene, ".feat-rule"), { scaleX: 0 }, { scaleX: 1, duration: 0.4 }, start + 0.4);
      const items = qa(scene, ".feat");
      const step = Math.min(0.6, Math.max(0.2, (dur - 1) / Math.max(1, items.length)));
      items.forEach((f, k) => tl.fromTo(f, { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.35 }, start + 0.55 + k * step));
    } else if (layout === "price") {
      tl.fromTo(q(scene, ".thumb"), { scale: 0.7, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4 }, start);
      const old = q(scene, ".price-old");
      if (old) tl.fromTo(old, { y: -30, opacity: 0 }, { y: 0, opacity: 1, duration: 0.35 }, start + 0.15);
      const big = q(scene, ".price-big");
      tl.fromTo(big, { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5 }, start + 0.35);
      shine(big, start + 0.9);
      const badge = q(scene, ".price-badge");
      if (badge) tl.fromTo(badge, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.35 }, start + 0.8);
      const note = q(scene, ".price-note");
      if (note) tl.fromTo(note, { opacity: 0 }, { opacity: 1, duration: 0.3 }, start + 1.0);
    } else if (layout === "callout") {
      tl.fromTo(q(scene, ".thumb"), { scale: 0.7, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4 }, start);
      tl.fromTo(q(scene, ".callout-card"), { y: 60, scale: 0.92, opacity: 0 }, { y: 0, scale: 1, opacity: 1, duration: 0.5 }, start + 0.15);
    } else if (layout === "outro") {
      tl.fromTo(q(scene, ".thumb"), { scale: 0.7, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.4 }, start);
      tl.fromTo(q(scene, ".outro-cta"), { scale: 0.6, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45 }, start + 0.1);
      const arrow = q(scene, ".outro-arrow");
      tl.fromTo(arrow, { y: -20, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3 }, start + 0.45);
      for (let k = 0; k < 3; k++) {
        tl.to(arrow, { y: 18, duration: 0.25 }, start + 0.8 + k * 0.5);
        tl.to(arrow, { y: 0, duration: 0.25 }, start + 1.05 + k * 0.5);
      }
      const card = q(scene, ".follow-card");
      const at = start + Math.min(1.2, dur * 0.35);
      tl.fromTo(card, { y: 200, opacity: 0 }, { y: 0, opacity: 1, duration: 0.45 }, at);
      tl.to(q(scene, ".follow-btn"), { scale: 0.9, duration: 0.12 }, at + 0.8);
      tl.to(q(scene, ".follow-btn"), { scale: 1, duration: 0.25 }, at + 0.92);
      tl.to(q(scene, ".fb-follow"), { opacity: 0, duration: 0.08 }, at + 0.92);
      tl.to(q(scene, ".fb-done"), { opacity: 1, duration: 0.08 }, at + 0.94);
    }

    // phụ đề: sáng dần từng chữ, thời điểm chia theo số ký tự
    const words = qa(scene, ".sub .w");
    const total = words.reduce((s, w) => s + w.textContent.length + 1, 0);
    const speak = Math.max(0.6, dur - (idx === scenes.length - 1 ? 0.8 : 0.25));
    let acc = 0;
    words.forEach((w) => {
      tl.to(w, { opacity: 1, duration: 0.12 }, start + (acc / total) * speak);
      acc += w.textContent.length + 1;
    });
    tl.fromTo(q(scene, ".sub-inner"), { y: 30, opacity: 0 }, { y: 0, opacity: 1, duration: 0.25 }, start);
  });
})();
