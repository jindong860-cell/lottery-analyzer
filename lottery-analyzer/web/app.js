/* 彩票分析助手 Web 端逻辑：原生 JS，无依赖。所有数据经同一后端 /api/*。 */
"use strict";

const $ = (id) => document.getElementById(id);
let state = {
  game: "dlt",
  page: 1,
  pageSize: 20,
  lastFreq: null,   // 供走势网格复用
};

// ---------------------------------------------------------------- 基础请求

async function api(path, options = {}) {
  const resp = await fetch(path, options);
  let body = null;
  try { body = await resp.json(); } catch (e) { body = { error: "非 JSON 响应" }; }
  if (!resp.ok) throw new Error(body.error || (`HTTP ${resp.status}`));
  return body;
}
const getJSON = (p) => api(p);
const postJSON = (p, data) => api(p, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data || {}),
});

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function ballEl(n, cls) {
  const s = document.createElement("span");
  s.className = "ball " + cls;
  s.textContent = String(n).padStart(2, "0");
  return s;
}

function toast(id, msg) { const el = $(id); if (el) { el.textContent = msg; setTimeout(() => { el.textContent = ""; }, 6000); } }

// ---------------------------------------------------------------- 标签页

document.querySelectorAll("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "stats" && !state.lastFreq) loadStats();
    if (btn.dataset.tab === "model") loadRuns();
    if (btn.dataset.tab === "scratch") { loadSamples(); loadAccuracy(); loadProfiles(); }
  });
});

// ---------------------------------------------------------------- 开奖数据

async function health() {
  try {
    const out = await getJSON("/api/health");
    $("health").textContent = "服务正常 · 彩种: " + out.games.join(", ");
  } catch (e) {
    const el = $("health");
    if (location.protocol === "file:") {
      el.innerHTML = "当前页面是直接双击打开的（file://），无法调用后端接口。请先启动后端：进入 <code>lottery-analyzer/server</code> 双击 <code>启动后端.bat</code>（或运行 <code>python run_server.py</code>），然后访问 <a href=\"http://127.0.0.1:8000/\">http://127.0.0.1:8000/</a>";
    } else {
      el.innerHTML = "后端未启动（" + esc(e.message) + "）。请进入 <code>lottery-analyzer/server</code> 双击 <code>启动后端.bat</code>（或运行 <code>python run_server.py</code>），启动后刷新本页。";
    }
  }
}

async function loadDraws() {
  const game = state.game;
  const out = await getJSON(`/api/draws?game=${game}&page=${state.page}&page_size=${state.pageSize}`);
  $("draw-count").textContent = `（共 ${out.total} 期）`;
  $("page-info").textContent = `第 ${out.page} / ${Math.max(1, Math.ceil(out.total / out.page_size))} 页`;
  const gnames = { ssq: ["红球", "蓝球"], dlt: ["前区", "后区"] }[game];
  $("th-front").textContent = gnames[0];
  $("th-back").textContent = gnames[1];
  const tb = $("draw-table").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of out.rows) {
    const tr = document.createElement("tr");
    const reds = td => td;
    tr.innerHTML = `<td>${esc(r.issue)}</td><td>${esc(r.draw_date)}</td><td class="balls"></td><td class="balls"></td>`;
    const c1 = tr.children[2], c2 = tr.children[3];
    r.reds.forEach((n) => c1.appendChild(ballEl(n, "red")));
    r.blues.forEach((n) => c2.appendChild(ballEl(n, "blue")));
    tb.appendChild(tr);
  }
}

async function loadSyncLog() {
  const out = await getJSON("/api/draws/synclog");
  const tb = $("synclog-table").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of out.rows.slice(0, 15)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(r.ts)}</td><td>${esc(r.game)}</td>
      <td>${r.ok ? "✅" : "❌"}</td><td>${r.fetched}/${r.inserted}/${r.updated}</td>
      <td class="muted">${esc(r.message)}</td>`;
    tb.appendChild(tr);
  }
}

async function sync(mode) {
  const btnLock = (lock) => { ["btn-sync-inc", "btn-sync-full"].forEach((id) => $(id).disabled = lock); };
  btnLock(true);
  toast("sync-status", "同步中…");
  try {
    const out = await postJSON("/api/draws/sync", { game: state.game, mode });
    toast("sync-status", `完成：拉取 ${out.fetched} 期，新增 ${out.inserted}，更新 ${out.updated}，库内 ${out.total_in_db} 期`);
    state.page = 1;
    await loadDraws();
    await loadSyncLog();
  } catch (e) {
    toast("sync-status", "同步失败：" + e.message);
  } finally { btnLock(false); }
}

// ---------------------------------------------------------------- 统计分析

async function loadStats() {
  const game = state.game;
  const win = parseInt($("stat-window").value || "0", 10);
  const freq = await getJSON(`/api/stats/frequency?game=${game}&window=${win}`);
  state.lastFreq = freq;
  drawFreqChart(freq);
  const tb = $("freq-table").querySelector("tbody");
  tb.innerHTML = "";
  freq.front.forEach((x) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${x.num}</td><td>${x.count}</td><td>${x.rate == null ? "-" : (x.rate * 100).toFixed(2) + "%"}</td>`;
    tb.appendChild(tr);
  });
  const om = await getJSON(`/api/stats/omission?game=${game}`);
  const tb2 = $("omit-table").querySelector("tbody");
  tb2.innerHTML = "";
  om.front.forEach((x) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${x.num}</td><td>${x.current}</td><td>${x.max}</td><td>${x.avg == null ? "从未开出" : x.avg}</td>`;
    tb2.appendChild(tr);
  });
  const tr_ = await getJSON(`/api/stats/trend?game=${game}&last_n=30`);
  renderTrend(tr_);
}

function drawFreqChart(freq) {
  const canvas = $("freq-canvas");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const data = freq.front;
  const maxC = Math.max(1, ...data.map((d) => d.count));
  const pad = 28, W = canvas.width - pad * 2, H = canvas.height - 36;
  const bw = W / data.length;
  ctx.font = "10px sans-serif";
  data.forEach((d, i) => {
    const h = (d.count / maxC) * H;
    const x = pad + i * bw + 1;
    ctx.fillStyle = "#dc2626";
    ctx.fillRect(x, 18 + H - h, Math.max(2, bw - 3), h);
    ctx.fillStyle = "#475569";
    if (bw > 14) ctx.fillText(d.num, x + (bw - 3) / 2 - 4, canvas.height - 14);
    if (bw > 20 && d.count > 0) {
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(d.count, x + (bw - 3) / 2 - 4, 14 + H - h);
    }
  });
  ctx.fillStyle = "#64748b";
  ctx.fillText(`最近 ${freq.draw_count} 期 · 前区号码出现期数`, pad, 10);
}

function renderTrend(t) {
  const grid = $("trend-grid");
  grid.innerHTML = "";
  for (const row of t.rows) {
    const div = document.createElement("div");
    div.className = "trend-row";
    const label = document.createElement("span");
    label.className = "trend-issue";
    label.textContent = `${row.issue}（${row.draw_date.slice(5)}）`;
    div.appendChild(label);
    const hitF = new Set(row.reds), hitB = new Set(row.blues);
    for (let n = 1; n <= t.front_max; n++) {
      const c = document.createElement("span");
      c.className = "trend-cell" + (hitF.has(n) ? " hit" : "");
      c.textContent = n;
      div.appendChild(c);
    }
    for (let n = 1; n <= t.back_max; n++) {
      const c = document.createElement("span");
      c.className = "trend-cell" + (hitB.has(n) ? " hitb" : "");
      c.textContent = n;
      div.appendChild(c);
    }
    grid.appendChild(div);
  }
}

// ---------------------------------------------------------------- 模型与回测

async function loadRuns() {
  const out = await getJSON(`/api/model/runs?game=${state.game}&limit=20`);
  const tb = $("runs-table").querySelector("tbody");
  tb.innerHTML = "";
  for (const r of out.rows) {
    const tr = document.createElement("tr");
    const m = r.metrics || {};
    tr.innerHTML = `<td>#${r.id}</td><td>${esc(r.game)}</td><td>${r.window}</td><td>${r.test_ratio}</td>
      <td>${r.train_samples}/${r.test_samples}</td>
      <td>${m.auc == null ? "-" : m.auc}</td><td>${m.log_loss}</td><td>${m.brier}</td>
      <td class="muted">${esc(r.created_at)}</td>
      <td><button data-run="${r.id}">报告</button></td>`;
    tr.querySelector("button").addEventListener("click", () => showRun(r.id));
    tb.appendChild(tr);
  }
  if (out.rows.length) showRun(out.rows[0].id);
}

async function showRun(id) {
  const r = await getJSON(`/api/model/runs/${id}`);
  $("run-id").textContent = `运行 #${r.id}（${r.game_name}）`;
  $("run-report").textContent = JSON.stringify(r.report, null, 2);
}

async function train() {
  const ratio = parseFloat($("m-test-ratio").value);
  const win = parseInt($("m-window").value, 10);
  toast("train-status", "训练中…");
  try {
    const out = await postJSON("/api/model/train", { game: state.game, test_ratio: ratio, window: win });
    toast("train-status", `完成：运行 #${out.run_id}，AUC=${out.metrics.auc}，Top${out.simulation.top_k} 平均命中 ${out.simulation.avg_hits}（随机基线 ${out.simulation.random_baseline_avg_hits}）`);
    await loadRuns();
  } catch (e) {
    toast("train-status", "失败：" + e.message);
  }
}

async function predict() {
  try {
    const out = await postJSON("/api/model/predict", { game: state.game });
    $("predict-basis").textContent = `基于运行 #${out.based_on_run_id}，样本 ${out.based_on_draws} 期（最新 ${out.latest_issue}）`;
    const box = $("predict-out");
    box.innerHTML = "";
    const picks = new Set(out.top_k.map((x) => x.num));
    out.all_probs.forEach((x) => box.appendChild(ballEl(x.num, picks.has(x.num) ? "red pick" : "")));
    $("predict-disclaimer").textContent = out.disclaimer;
  } catch (e) {
    $("predict-basis").textContent = "失败：" + e.message;
  }
}

// ---------------------------------------------------------------- 刮刮乐

async function loadProfileOptions() {
  const out = await getJSON("/api/scratch/profiles");
  const sel = $("scratch-hint");
  sel.innerHTML = '<option value="">自动识别</option>';
  out.profiles.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.name;
    sel.appendChild(o);
  });
}

async function upload() {
  const file = $("scratch-file").files[0];
  if (!file) { toast("upload-status", "请选择图片"); return; }
  toast("upload-status", "上传识别中…");
  const fd = new FormData();
  fd.append("image", file, file.name);
  const hint = $("scratch-hint").value;
  if (hint) fd.append("ticket_type_hint", hint);
  fd.append("device", "web");
  try {
    const out = await api("/api/scratch/samples", { method: "POST", body: fd });
    toast("upload-status", `已入库 #${out.id}，置信度 ${out.confidence}` + (out.needs_review ? "（需人工复核：" + out.review_reason + "）" : ""));
    const pv = $("upload-preview");
    pv.innerHTML = "";
    if (out.image_url) { const img = new Image(); img.src = out.image_url; img.className = "preview"; pv.appendChild(img); }
    if (out.roi_url) { const img = new Image(); img.src = out.roi_url; img.className = "preview"; pv.appendChild(img); }
    const info = document.createElement("div");
    info.innerHTML = `票种: ${esc(out.ticket_type || "-")} · OCR(${esc(out.ocr_engine)}): ${esc(out.ocr_text || "-")}
      <br>预测: ${esc(out.predicted_rank || "-")} / ${out.predicted_amount == null ? "-" : out.predicted_amount + "元"}`;
    pv.appendChild(info);
    await loadSamples(); await loadAccuracy();
  } catch (e) {
    toast("upload-status", "失败：" + e.message);
  }
}

async function loadSamples() {
  const out = await getJSON("/api/scratch/samples?limit=50");
  const tb = $("samples-table").querySelector("tbody");
  tb.innerHTML = "";
  const statusText = { pending: "待录入", match: "✅ 命中", mismatch: "❌ 不符", review: "⚠ 人工复核" };
  for (const s of out.rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.id}</td><td class="muted">${esc(s.created_at)}</td><td>${esc(s.ticket_type || "-")}</td>
      <td>${esc(s.predicted_rank || "-")}</td><td>${s.predicted_amount == null ? "-" : s.predicted_amount}</td>
      <td>${s.confidence == null ? "-" : s.confidence}</td><td>${statusText[s.match_status] || s.match_status}</td>
      <td class="muted">${esc(s.review_reason || "")}</td><td></td>`;
    const op = tr.lastElementChild;
    const btn = document.createElement("button");
    btn.textContent = "录入结果";
    btn.addEventListener("click", () => verifyDialog(s));
    op.appendChild(btn);
    tb.appendChild(tr);
  }
}

function verifyDialog(sample) {
  const rank = prompt(`样本 #${sample.id} 实际奖级（如：${sample.predicted_rank || "100元档"}；留空跳过）`, "");
  if (rank === null) return;
  const amount = prompt("实际金额（数字，元；留空跳过）", "");
  if (amount === null) return;
  if (!rank && !amount) { alert("必须至少提供奖级或金额之一"); return; }
  postJSON(`/api/scratch/samples/${sample.id}/verify`, {
    actual_rank: rank || null,
    actual_amount: amount ? parseInt(amount, 10) : null,
  }).then(() => { loadSamples(); loadAccuracy(); })
    .catch((e) => alert("失败：" + e.message));
}

async function loadAccuracy() {
  const out = await getJSON("/api/scratch/accuracy");
  const el = $("accuracy-out");
  if (!out.total) { el.textContent = "暂无数据"; return; }
  const a = out.auto_verified;
  el.innerHTML = `样本总数 ${out.total} · 待录入 ${out.by_status.pending || 0} · 人工复核 ${out.by_status.review || 0}
    · 系统有预测且已验证 ${a.total} 条，命中 ${a.match}，不符 ${a.mismatch}，
    准确率 <b>${a.accuracy == null ? "-" : (a.accuracy * 100).toFixed(1) + "%"}</b>
    <br>按票种：${out.by_ticket_type.map((t) => `${esc(t.ticket_type)}：${t.judged} 条，${t.accuracy == null ? "-" : (t.accuracy * 100).toFixed(1) + "%"}`).join("；")}`;
}

async function loadProfiles() {
  const out = await getJSON("/api/scratch/profiles");
  $("profiles-json").value = JSON.stringify(out, null, 2);
}

async function saveProfiles() {
  try {
    const data = JSON.parse($("profiles-json").value);
    const out = await api("/api/scratch/profiles", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    toast("profiles-status", `已保存 ${out.profiles.length} 个票种模板`);
  } catch (e) {
    toast("profiles-status", "失败：" + e.message);
  }
}

// ---------------------------------------------------------------- 事件绑定与初始化

$("game-select").addEventListener("change", (e) => {
  state.game = e.target.value; state.page = 1;
  loadDraws(); loadSyncLog();
  if (state.lastFreq) loadStats();
  loadRuns();
});
$("btn-sync-inc").addEventListener("click", () => sync("incremental"));
$("btn-sync-full").addEventListener("click", () => sync("full"));
$("page-prev").addEventListener("click", () => { if (state.page > 1) { state.page--; loadDraws(); } });
$("page-next").addEventListener("click", () => { state.page++; loadDraws().catch(() => { state.page--; }); });
$("btn-stats").addEventListener("click", () => loadStats().catch((e) => alert(e.message)));
$("btn-train").addEventListener("click", () => train());
$("btn-predict").addEventListener("click", () => predict());
$("btn-upload").addEventListener("click", () => upload());
$("btn-profiles-save").addEventListener("click", () => saveProfiles());

health();
loadProfileOptions();
loadDraws().catch((e) => toast("sync-status", e.message));
loadSyncLog();
