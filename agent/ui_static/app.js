"use strict";
// Giao diện điều khiển agent. Dữ liệu từ /api/state (2,5 giây/lần), log lệnh từ /api/jobs/<id> (1 giây/lần).

const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (sel, el = document) => el.querySelector(sel);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

const QUEUE_LABEL = {
  moi: "Mới", dang_lam: "Đang làm", cho_duyet: "Chờ duyệt", da_len_lich: "Đã lên lịch",
  da_dang: "Đã đăng", bo_qua: "Bỏ qua", loi: "Lỗi",
};
const JOB_LABEL = { cho: "Đang chờ", dang_chay: "Đang chạy", xong: "Xong", loi: "Lỗi", da_dung: "Đã dừng" };
const JOB_DONE = ["xong", "loi", "da_dung"];
const APPROVAL_LABEL = { duyet_tung_video: "Duyệt từng video", duyet_theo_lo: "Duyệt theo lô", tu_dang_facebook: "Tự đăng Facebook" };
const PLATFORM_LABEL = { facebook: "Facebook Reels", tiktok: "TikTok", both: "Facebook + TikTok" };
const TASK_NEVER_RAN = 267011; // mã Task Scheduler: tác vụ chưa chạy lần nào

const saved = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* trình duyệt chặn lưu trữ */ } },
};

let state = null;
let queueFilter = saved.get("queueFilter", "all");
const drawn = {};                                     // chữ ký dữ liệu đã vẽ: không đổi thì không vẽ lại (video không bị dừng)
const log = { job: null, next: 0, done: true, daily: null, busy: false };

// ---------- tiện ích ----------

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Token": TOKEN },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Lỗi ${r.status}`);
  return data;
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4500);
}

const pad = (n) => String(n).padStart(2, "0");
function fmtTime(v) {
  if (!v) return "";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  return s < 60 ? `${s} giây` : `${Math.floor(s / 60)} phút ${pad(s % 60)} giây`;
}
function shortUrl(u) {
  try { const x = new URL(u); const s = x.host + x.pathname; return s.length > 70 ? s.slice(0, 69) + "…" : s; }
  catch { return u; }
}
const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "#");
const opts = (list) => list.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");

function draw(key, data, fn) {
  const sig = JSON.stringify(data);
  if (drawn[key] !== sig) { drawn[key] = sig; fn(); }
}

// ---------- tải dữ liệu ----------

async function refresh() {
  try {
    state = await api("/api/state");
    setConn(true);
  } catch {
    setConn(false);
    return;
  }
  draw("settings", [state.settings, state.schedule], renderSettings);
  draw("queue", [state.queue, queueFilter, state.products.map((p) => p.slug)], renderQueue);
  renderProducts(state.products);
  draw("jobs", [state.jobs.map((j) => [j.id, j.status, j.position]), log.job], renderJobs);
  draw("daily", [state.daily_logs, state.schedule, log.daily], renderDaily);
  if (!log.job && !log.daily && state.jobs.length) {
    const active = state.jobs.find((j) => j.status === "dang_chay");
    selectJob((active || state.jobs[0]).id);  // mới mở trang: xem lệnh đang chạy, hoặc lệnh gần nhất
  }
}

function setConn(ok) {
  const el = $("#conn");
  el.textContent = ok ? "Đang chạy trên máy này" : "Mất kết nối. Cửa sổ giao diện đã bị tắt?";
  el.className = `conn ${ok ? "ok" : "bad"}`;
}

// ---------- vẽ ----------

function renderSettings() {
  const s = state.settings;
  const chips = [
    ["Chế độ", APPROVAL_LABEL[s.APPROVAL_MODE] || s.APPROVAL_MODE],
    ["Dựng", s.VIDEO_ENGINE],
    ["Giọng", s.TTS_PROVIDER],
    ["Tối đa", `${s.MAX_PER_DAY} video/ngày`],
    ["Giỏ TikTok", s.TIKTOK_HAS_CART === "true" ? "Có" : "Chưa"],
    ["Shopee API", s.SHOPEE_API ? "Có" : "Chưa", s.SHOPEE_API ? "" : "dim"],
    ["Claude CLI", s.CLAUDE_CLI ? "Sẵn sàng" : "Chưa cài", s.CLAUDE_CLI ? "" : "bad"],
  ];
  if (s.CLAUDE_CLI && s.CLAUDE_TRUSTED === false) chips.push(["Quyền Claude", "Chưa tin thư mục", "bad"]);
  $("#settings").innerHTML = chips
    .map(([k, v, cls]) => `<span class="chip ${cls || ""}"><b>${esc(k)}</b> ${esc(v)}</span>`).join("");
}

function renderQueue() {
  const rows = state.queue;
  const counts = {};
  rows.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });
  const tabs = [["all", "Tất cả", rows.length],
    ...Object.keys(QUEUE_LABEL).filter((k) => counts[k]).map((k) => [k, QUEUE_LABEL[k], counts[k]])];
  if (!tabs.some((t) => t[0] === queueFilter)) queueFilter = "all";
  $("#queue-tabs").innerHTML = tabs.map(([k, label, n]) =>
    `<button type="button" class="tab ${k === queueFilter ? "on" : ""}" data-act="filter" data-status="${esc(k)}">${esc(label)} <span>${n}</span></button>`).join("");
  const shown = queueFilter === "all" ? rows : rows.filter((r) => r.status === queueFilter);
  $("#queue").innerHTML = shown.length ? shown.map(queueRow).join("")
    : `<p class="empty">${rows.length ? "Không có link ở trạng thái này." : "Chưa có link nào. Dán link sản phẩm ở ô phía trên."}</p>`;
}

function queueRow(r) {
  const acts = [];
  if (["moi", "loi", "bo_qua"].includes(r.status)) {
    acts.push(`<button type="button" class="btn sm primary" data-act="lam-video" data-target="${esc(r.id)}">Làm video</button>`);
  }
  if (r.status === "moi") {
    acts.push(`<button type="button" class="btn sm ghost" data-act="set" data-id="${esc(r.id)}" data-status="bo_qua">Bỏ qua</button>`);
  }
  if (["loi", "bo_qua"].includes(r.status)) {
    acts.push(`<button type="button" class="btn sm ghost" data-act="set" data-id="${esc(r.id)}" data-status="moi">Đưa về "Mới"</button>`);
  }
  if (r.slug && state.products.some((p) => p.slug === r.slug)) {
    acts.push(`<button type="button" class="btn sm" data-act="goto" data-slug="${esc(r.slug)}">Xem video</button>`);
  }
  return `<div class="qrow">
    <span class="badge s-${esc(r.status)}">${esc(QUEUE_LABEL[r.status] || r.status)}</span>
    <div class="qmain">
      <a href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">${esc(shortUrl(r.url))}</a>
      <div class="qmeta">${esc(r.platform)} · id ${esc(r.id)} · ${esc(fmtTime(r.updated_at))}${r.note ? ` · ${esc(r.note)}` : ""}</div>
      ${r.agent_note ? `<p class="agent-note">${esc(r.agent_note)}</p>` : ""}
    </div>
    <div class="qacts">${acts.join("")}</div>
  </div>`;
}

function renderProducts(products) {
  const box = $("#products");
  if (!products.length) {
    if (drawn.products !== "empty") {
      box.innerHTML = `<p class="empty">Chưa có sản phẩm nào. Bấm "Làm video" ở hàng đợi để bắt đầu.</p>`;
      drawn.products = "empty";
    }
    return;
  }
  if (drawn.products === "empty") box.innerHTML = "";
  drawn.products = "list";
  const els = products.map((p) => {
    const sig = JSON.stringify(p);
    let el = [...box.children].find((c) => c.dataset.slug === p.slug);
    if (!el || el.dataset.sig !== sig) {
      const fresh = productCard(p);
      fresh.dataset.sig = sig;
      if (el) el.replaceWith(fresh);
      el = fresh;
    }
    return el;
  });
  const same = els.length === box.children.length && els.every((el, i) => box.children[i] === el);
  if (!same) box.replaceChildren(...els);
}

const PLATFORM_OPTS = [["both", "Cả hai"], ["facebook", "Facebook"], ["tiktok", "TikTok"]];

function productCard(p) {
  const el = document.createElement("article");
  el.className = "product";
  el.id = `p-${p.slug}`;
  el.dataset.slug = p.slug;
  const built = Object.keys(p.outputs).length > 0;
  const q = p.queue;
  el.innerHTML = `
    <header class="p-head">
      ${p.image ? `<img class="thumb" src="${esc(p.image)}" alt="">` : `<div class="thumb"></div>`}
      <div class="p-title">
        <h3>${esc(p.name)}</h3>
        <div class="p-sub">
          ${p.price ? `<span class="price">${esc(p.price)}</span>` : ""}
          <code>${esc(p.slug)}</code>
          ${q ? `<span class="badge s-${esc(q.status)}">${esc(QUEUE_LABEL[q.status] || q.status)}</span>` : ""}
        </div>
      </div>
      <button type="button" class="btn sm ghost" data-act="open" data-slug="${esc(p.slug)}">Mở thư mục</button>
    </header>
    ${p.needs.length ? `<ul class="needs">${p.needs.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    ${q && q.agent_note ? `<p class="agent-note">${esc(q.agent_note)}</p>` : ""}
    <div class="outs">${["facebook", "tiktok"].map((k) => outBlock(p, k)).join("")}</div>
    <div class="p-actions">
      <form class="inline" data-action="render" data-slug="${esc(p.slug)}">
        <select name="platform" aria-label="Nền tảng">${opts(PLATFORM_OPTS)}</select>
        <select name="engine" aria-label="Kiểu dựng">${opts([["", "Kiểu dựng: mặc định"], ["ffmpeg", "ffmpeg (nhanh)"], ["hyperframes", "hyperframes (motion)"]])}</select>
        <select name="tts" aria-label="Giọng đọc">${opts([["", "Giọng: mặc định"], ["edge", "edge (miễn phí)"], ["elevenlabs", "ElevenLabs"], ["fpt", "FPT.AI"], ["silent", "Không tiếng"]])}</select>
        <button class="btn" ${p.scripts.length ? "" : 'disabled title="Chưa có kịch bản"'}>${built ? "Dựng lại" : "Dựng video"}</button>
      </form>
      <form class="inline" data-action="duyet" data-slug="${esc(p.slug)}" data-confirm="1">
        <select name="platform" aria-label="Nền tảng đăng">${opts(PLATFORM_OPTS)}</select>
        <input name="time" placeholder="Giờ đăng, vd: 20:00 mai (bỏ trống = giờ tốt nhất)" maxlength="40">
        <button class="btn primary" ${built ? "" : 'disabled title="Chưa có video"'}>Duyệt và lên lịch</button>
      </form>
    </div>`;
  return el;
}

function outBlock(p, k) {
  const o = p.outputs[k];
  if (!o) {
    return `<div class="out"><div class="out-title">${PLATFORM_LABEL[k]}</div>
      <div class="video ph">${p.scripts.includes(k) ? "Chưa dựng" : "Chưa có kịch bản"}</div></div>`;
  }
  const m = o.meta || {};
  const info = [m.seconds != null ? `${m.seconds} giây` : "", m.engine || "ffmpeg", fmtTime(o.built_at)].filter(Boolean).join(" · ");
  return `<div class="out">
    <div class="out-title">${PLATFORM_LABEL[k]}<span class="muted">${esc(info)}</span></div>
    <video class="video" controls preload="metadata" playsinline src="${esc(o.video)}"${o.cover ? ` poster="${esc(o.cover)}"` : ""}></video>
    ${(m.warnings || []).map((w) => `<p class="warn">${esc(w)}</p>`).join("")}
    <details><summary>Caption</summary>
      <pre class="caption">${esc(o.caption)}</pre>
      <button type="button" class="btn sm" data-act="copy" data-slug="${esc(p.slug)}" data-platform="${k}">Sao chép caption</button>
    </details>
  </div>`;
}

function renderJobs() {
  const jobs = state ? state.jobs : [];
  $("#jobs").innerHTML = jobs.length ? jobs.map((j) => `
    <button type="button" class="job ${j.id === log.job ? "on" : ""}" data-act="job" data-id="${esc(j.id)}">
      <span class="dot j-${esc(j.status)}"></span>
      <span class="job-title">${esc(j.title)}</span>
      <span class="job-meta">${esc(JOB_LABEL[j.status] || j.status)}${j.position ? ` · thứ ${j.position} trong hàng chờ` : ""}
        · <span class="elapsed" data-start="${j.started || ""}" data-end="${j.ended || ""}"></span></span>
    </button>`).join("") : `<p class="empty small">Chưa chạy lệnh nào. Bấm một nút bên trái để bắt đầu.</p>`;
  tick();
}

function tick() {
  const now = Date.now() / 1000;
  document.querySelectorAll(".elapsed").forEach((el) => {
    const start = parseFloat(el.dataset.start);
    const end = parseFloat(el.dataset.end) || now;
    el.textContent = start ? fmtDur(end - start) : "chưa chạy";
  });
}

function renderDaily() {
  const sc = state.schedule;
  let head = "";
  if (sc && sc.missing) {
    head = `<p class="small muted">Chưa có tác vụ "Affiliate agent" trong Task Scheduler.</p>`;
  } else if (sc) {
    const last = sc.result === TASK_NEVER_RAN ? "chưa chạy lần nào"
      : `${fmtTime(sc.last)} (${sc.result === 0 ? "ổn" : `mã ${sc.result}`})`;
    head = `<p class="small muted">Lần tới: <b>${esc(fmtTime(sc.next))}</b> · Lần trước: ${esc(last)}</p>`;
  }
  const names = state.daily_logs;
  $("#daily").innerHTML = head + (names.length
    ? names.map((n) => `<button type="button" class="tab ${n === log.daily ? "on" : ""}" data-act="daily" data-name="${esc(n)}">${esc(n.replace(".log", ""))}</button>`).join("")
    : `<p class="small muted">Chưa có nhật ký nào.</p>`);
}

// ---------- log ----------

function selectJob(id) {
  Object.assign(log, { job: id, daily: null, next: 0, done: false });
  $("#log").textContent = "";
  drawn.loghead = null;
  if (state) {
    drawn.jobs = drawn.daily = null;
    renderJobs();
    renderDaily();
  }
  pollLog();
}

async function pollLog() {
  if (!log.job || log.done || log.busy) return;
  log.busy = true;
  const id = log.job;
  try {
    const d = await api(`/api/jobs/${encodeURIComponent(id)}?since=${log.next}`);
    if (id !== log.job) return;
    appendLog(d.lines);
    log.next = d.next;
    draw("loghead", [d.job.id, d.job.status], () => renderLogHead(d.job));
    log.done = JOB_DONE.includes(d.job.status);
  } catch (e) {
    if (id === log.job) {
      log.done = true;
      $("#log-head").innerHTML = `<span class="muted">${esc(e.message)}</span>`;
    }
  } finally {
    log.busy = false;
  }
}

function appendLog(lines) {
  if (!lines.length) return;
  const pre = $("#log");
  const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
  const frag = document.createDocumentFragment();
  for (const l of lines) {
    const span = document.createElement("span");
    span.className = `k-${l.k}`;
    span.textContent = `${l.s}\n`;
    frag.append(span);
  }
  pre.append(frag);
  if (atBottom) pre.scrollTop = pre.scrollHeight;
}

function renderLogHead(j) {
  const active = !JOB_DONE.includes(j.status);
  $("#log-head").innerHTML = `<div><b>${esc(j.title)}</b> <span class="muted">· ${esc(JOB_LABEL[j.status] || j.status)}</span></div>
    ${active ? `<button type="button" class="btn sm danger" data-act="stop" data-id="${esc(j.id)}">Dừng</button>` : ""}`;
}

async function showDaily(name) {
  Object.assign(log, { job: null, daily: name, done: true });
  drawn.jobs = drawn.daily = drawn.loghead = null;
  renderJobs();
  renderDaily();
  $("#log-head").innerHTML = `<div><b>Nhật ký chạy tự động ${esc(name.replace(".log", ""))}</b></div>`;
  $("#log").textContent = "Đang tải…";
  try {
    const d = await api(`/api/daily-log/${encodeURIComponent(name)}`);
    $("#log").textContent = d.text || "(trống)";
  } catch (e) {
    $("#log").textContent = e.message;
  }
}

// ---------- hành động ----------

function confirmText(action, p = {}) {
  const s = state ? state.settings : {};
  if (action === "chay-hang-ngay") {
    return `Chạy phiên hằng ngày ngay bây giờ?\n\nClaude sẽ xử lý tối đa ${s.MAX_PER_DAY || 2} link mới trong hàng đợi và dùng hạn mức gói Claude của bạn.`
      + (s.APPROVAL_MODE === "tu_dang_facebook" ? "\nChế độ hiện tại cho phép tự lên lịch đăng Facebook." : "");
  }
  if (action === "duyet") {
    return `Duyệt và lên lịch đăng ${PLATFORM_LABEL[p.platform] || p.platform} cho "${p.slug}"${p.time ? ` lúc ${p.time}` : ""}?\n\nClaude sẽ lên lịch qua Metricool.`;
  }
  return null;
}

async function run(action, params = {}, ask = null) {
  if (ask && !confirm(ask)) return;
  try {
    const { job } = await api("/api/run", { action, ...params });
    const busy = state && state.jobs.some((j) => j.status === "dang_chay");
    toast(busy ? `Đã xếp hàng: ${job.title} (chạy sau khi lệnh hiện tại xong)` : `Đã bắt đầu: ${job.title}`, "ok");
    selectJob(job.id);
    refresh();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function post(path, body, okMsg) {
  try {
    await api(path, body);
    if (okMsg) toast(okMsg, "ok");
    refresh();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function addLink(runNow) {
  const url = $("#add-url").value.trim();
  const note = $("#add-note").value.trim();
  if (!url) return;
  try {
    const d = await api("/api/queue/add", { url, note, run: runNow });
    $("#add-url").value = "";
    $("#add-note").value = "";
    toast(runNow ? `Đã thêm (id ${d.row.id}) và bắt đầu làm video` : `Đã thêm vào hàng đợi (id ${d.row.id})`, "ok");
    if (d.job) selectJob(d.job.id);
    refresh();
  } catch (e) {
    toast(e.message, "err");
  }
}

async function copyCaption(slug, platform) {
  const p = state && state.products.find((x) => x.slug === slug);
  const text = (p && p.outputs[platform] && p.outputs[platform].caption) || "";
  try {
    await navigator.clipboard.writeText(text);
    toast("Đã sao chép caption", "ok");
  } catch {
    toast("Không sao chép được. Hãy bôi đen caption rồi bấm Ctrl+C.", "err");
  }
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const d = b.dataset;
  switch (d.act) {
    case "filter":
      queueFilter = d.status;
      saved.set("queueFilter", d.status);
      drawn.queue = null;
      renderQueue();
      break;
    case "run": run(d.action, {}, d.confirm ? confirmText(d.action) : null); break;
    case "lam-video": run("lam-video", { target: d.target }); break;
    case "set": post("/api/queue/set", { id: d.id, status: d.status }, "Đã cập nhật hàng đợi"); break;
    case "goto": document.getElementById(`p-${d.slug}`)?.scrollIntoView({ behavior: "smooth", block: "start" }); break;
    case "open": post("/api/open", { slug: d.slug }); break;
    case "copy": copyCaption(d.slug, d.platform); break;
    case "job": selectJob(d.id); break;
    case "stop": post(`/api/jobs/${encodeURIComponent(d.id)}/stop`, {}, "Đã gửi lệnh dừng"); break;
    case "daily": showDaily(d.name); break;
    default: break;
  }
});

document.addEventListener("submit", (e) => {
  const f = e.target;
  e.preventDefault();
  if (f.id === "add-form") {
    addLink(!e.submitter || e.submitter.dataset.run === "1");
    return;
  }
  const params = { ...Object.fromEntries(new FormData(f)), slug: f.dataset.slug };
  run(f.dataset.action, params, f.dataset.confirm ? confirmText(f.dataset.action, params) : null);
});

refresh();
setInterval(refresh, 2500);
setInterval(() => { pollLog(); tick(); }, 1000);
