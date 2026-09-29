/* Poka-Yoke 조립 검증 — 화면.  서버가 주는 payload(web/pipeline.py) 를 그대로 그린다. 판정 로직은 없다.
   탭:  #work 작업(작업자)  #recipe 레시피  #history 이력  #analytics 분석  #diag 진단 */
(() => {
"use strict";

// ── 표시명 · 정책 ──────────────────────────────────────────
const NAME = { mother_part: "Mother (5구)", bolt_1: "노란 볼트 · 짧은", bolt_2: "주황 볼트 · 긴", part_2hole: "2구 파트", part_3hole: "3구 파트" };
const SHORT = { mother_part: "Mother", bolt_1: "노란 볼트", bolt_2: "주황 볼트", part_2hole: "2구 파트", part_3hole: "3구 파트" };
const CLASS_ORDER = ["mother_part", "bolt_1", "bolt_2", "part_2hole", "part_3hole"];
const PRIORITY = { WRONG_BOLT: 0, WRONG_PART: 0, UNEXPECTED_COMPONENT: 1, EXTRA_COMPONENT: 1, PART_ORIENTATION_ERROR: 2, MISSING_BOLT: 3, MISSING_PART: 3 };
const HOLD_TEXT = {
  MOTHER_ANGLE_OUT_OF_RANGE: (p) => [`Mother 가 ${fmtDeg(p.mother_angle_deg)} 기울었습니다`, `${p.timing.max_angle_deg}° 안쪽이어야 자리를 찾습니다. 손을 떼고 바로 놓으면 다시 봅니다.`],
  MOTHER_NOT_FOUND: () => ["Mother 가 안 보입니다", "카메라 안에 Mother 를 놓으세요."],
  MULTIPLE_MOTHERS: () => ["Mother 가 두 개 잡힙니다", "작업대에는 Mother 하나만 두세요."],
  AMBIGUOUS_ASSOCIATION: () => ["부품 위치를 판단할 수 없습니다", "손을 떼고 잠시 기다리세요."],
  INPUT_UNAVAILABLE: () => ["카메라 입력이 없습니다", "카메라 연결을 확인하세요."],
  FRAME_GAP: () => ["영상이 끊겼습니다", "잠시 뒤 자동으로 이어집니다."],
  OUT_OF_ORDER_FRAME: () => ["영상이 끊겼습니다", "잠시 뒤 자동으로 이어집니다."],
};
const HOLD_TITLE = { MOTHER_ANGLE_OUT_OF_RANGE: "Mother 각도 초과", MOTHER_NOT_FOUND: "Mother 안 보임", MULTIPLE_MOTHERS: "Mother 두 개", AMBIGUOUS_ASSOCIATION: "부품 위치 모호 (손 가림)", INPUT_UNAVAILABLE: "카메라 입력 없음", FRAME_GAP: "영상 끊김", OUT_OF_ORDER_FRAME: "영상 끊김" };
const fmtDeg = (d) => (d == null ? "?" : `${Math.abs(d).toFixed(0)}°`);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const chip = (cls, text, extra = "") => `<span class="chip ${cls} ${extra}">${esc(text)}</span>`;
const bolt = (c) => chip(c === "bolt_1" ? "b1" : "b2", SHORT[c]);
const part = (c) => chip("part", SHORT[c]);
const hhmmss = (ms) => { const d = new Date(ms); return d.toTimeString().slice(0, 8); };

function primaryIssue(issues) {
  const list = [...issues].sort((a, b) => (PRIORITY[a.code] ?? 9) - (PRIORITY[b.code] ?? 9) || a.hole_id - b.hole_id);
  return [list[0], list.slice(1)];
}
function human(i) {
  const h = `H${i.hole_id}`;
  switch (i.code) {
    case "WRONG_BOLT": return [`${h} 볼트가 다릅니다`, `${SHORT[i.expected]} 자리에 ${SHORT[i.observed]}`];
    case "WRONG_PART": return [`${h} 파트가 다릅니다`, `${SHORT[i.expected]} 자리에 ${SHORT[i.observed]}`];
    case "UNEXPECTED_COMPONENT": case "EXTRA_COMPONENT": return [`${h}에서 빼세요`, `${(i.observed || "").split(",").map((c) => SHORT[c] || c).join(", ")} — 이 자리는 비워 둡니다`];
    case "PART_ORIENTATION_ERROR": return [`${h} 파트를 똑바로 세우세요`, SHORT[i.observed] || ""];
    case "MISSING_BOLT": case "MISSING_PART": return [`${h} ${SHORT[i.expected] || ""} 아직`, "아직 안 꽂힘"];
    case "MATERIAL_MISSING": case "MATERIAL_EXCESS": case "MATERIAL_UNEXPECTED": {
      const [cls, need] = (i.expected || ":0").split(":"), have = (i.observed || ":0").split(":")[1];
      return [`${SHORT[cls] || cls} ${i.code === "MATERIAL_MISSING" ? "부족" : i.code === "MATERIAL_EXCESS" ? "초과" : "이 레시피에 없음"} (필요 ${need} · 있음 ${have})`, ""];
    }
    default: return [HOLD_TITLE[i.code] || i.code, ""];
  }
}

// ── 상태 ────────────────────────────────────────────────────
const S = { view: "work", p: null, rings: null, sub: "live", period: 7, events: [], hist: null, sel: null, ana: null, diag: null, recipes: null };
const $ = (sel, el = document) => el.querySelector(sel);
const main = $("#main"), hmid = $("#header-mid"), hright = $("#header-right");

// ── 연결: WebSocket, 안 되면 폴링 ──────────────────────────
let ws = null, pollTimer = null;
function connect() {
  try {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { $("#conn").classList.add("ok"); $("#conn").classList.remove("poll"); $("#conn").title = "서버 연결: WebSocket"; stopPoll(); };
    ws.onmessage = (e) => onPayload(JSON.parse(e.data));
    ws.onclose = ws.onerror = () => { $("#conn").classList.remove("ok"); startPoll(); setTimeout(connect, 3000); ws = null; };
  } catch (_) { startPoll(); }
}
// WebSocket 이 안 열리면(websockets 미설치 등) 200ms 폴링으로 같은 payload 를 받는다. 점은 노랑.
function startPoll() { if (pollTimer) return; pollTimer = setInterval(async () => { try { const p = await api("/api/state"); if (!p.waiting) { $("#conn").classList.add("ok", "poll"); $("#conn").title = "서버 연결: 폴링 (WebSocket 없음)"; onPayload(p); } } catch (_) { $("#conn").classList.remove("ok", "poll"); } }, 200); }
function stopPoll() { clearInterval(pollTimer); pollTimer = null; }
async function api(url, opt) { const r = await fetch(url, opt); return r.json(); }
const post = (url) => api(url, { method: "POST" });

function onPayload(p) {
  const prev = S.p; S.p = p;
  if (p.product_id !== prev?.product_id) S.events = [];
  S.events = p.events || S.events;
  if (p.stable || p.status === "HOLD" || p.phase !== "ASSEMBLING") S.rings = holeStates(p);
  if (S.view === "work" || S.view === "diag") render(prev && sameShape(prev, p));
}
function sameShape(a, b) {   // 큰 DOM 을 매 프레임 다시 그리지 않기 위한 키
  return a.phase === b.phase && a.status === b.status && a.stable === b.stable && a.product_id === b.product_id &&
    JSON.stringify(a.candidate) === JSON.stringify(b.candidate) && JSON.stringify(a.materials) === JSON.stringify(b.materials) &&
    a.recipe.recipe_id === b.recipe.recipe_id;
}

// ── 자리 상태 ────────────────────────────────────────────────
function holeStates(p) {
  const exp = {}; (p.recipe?.placements || []).forEach((pl) => (exp[pl.mother_hole] = pl));
  const out = {};
  for (let h = 1; h <= 5; h++) {
    if (p.phase !== "ASSEMBLING") { out[h] = "none"; continue; }
    if (p.candidate.status === "HOLD") { out[h] = "hold"; continue; }
    const iss = (p.candidate.issues || []).filter((i) => i.hole_id === h);
    const bad = iss.some((i) => !i.code.startsWith("MISSING")), missing = iss.some((i) => i.code.startsWith("MISSING"));
    out[h] = bad ? "ng" : exp[h] ? (missing ? "wait" : "ok") : "skip";
  }
  return out;
}
function observedAt(p, h) {
  const o = p.observed?.[String(h)]; if (!o) return { bolt: null, part: null };
  return { bolt: o.bolt?.[0]?.class_name || null, part: o.part?.[0]?.class_name || null };
}

// ── 라우팅 ──────────────────────────────────────────────────
window.addEventListener("hashchange", route);
function route() {
  S.view = (location.hash || "#work").slice(1);
  document.querySelectorAll("#sidebar a").forEach((a) => a.classList.toggle("on", a.dataset.view === S.view));
  render(false);
  if (S.view === "history") loadHistory();
  if (S.view === "analytics") loadAnalytics();
  if (S.view === "recipe") loadRecipes();
  if (S.view === "diag" && S.sub === "system") loadDiag();
}

function render(shapeSame) {
  const p = S.p;
  switch (S.view) {
    case "work": if (!shapeSame) { renderHeaderWork(p); main.innerHTML = viewWork(p); } drawOverlay(p, false); break;
    case "diag": if (!shapeSame) renderHeaderPeriod(); if (S.sub === "live") { if (!shapeSame) main.innerHTML = viewDiagLive(p); else updateDiagLive(p); drawOverlay(p, true); } else if (!shapeSame && S.diag) main.innerHTML = viewDiagSystem(S.diag); break;
    case "history": renderHeaderPeriod(); if (!shapeSame) main.innerHTML = viewHistory(); break;
    case "analytics": renderHeaderPeriod(); if (!shapeSame) main.innerHTML = viewAnalytics(); break;
    case "recipe": renderHeaderPlain("레시피", "config/recipes/*.json 을 그대로 읽습니다 · 수정은 파일에서"); if (!shapeSame) main.innerHTML = viewRecipe(); break;
  }
}

// ── 헤더 ────────────────────────────────────────────────────
function renderHeaderWork(p) {
  const recipes = p?.recipes || [], cur = p?.recipe?.recipe_id || "";
  const phase = p?.phase || "CHECK_MATERIALS";
  hmid.innerHTML = `
    <div class="recipe-sel"><span>레시피</span><select id="recipe-select">${recipes.map((r) => `<option ${r === cur ? "selected" : ""}>${r}</option>`).join("")}</select></div>
    <div class="stepper">
      <div class="${phase === "CHECK_MATERIALS" ? "on" : "done"}"><span class="dot">${phase === "CHECK_MATERIALS" ? "1" : "✓"}</span>재료 확인</div>
      <span class="bar"></span>
      <div class="${phase === "ASSEMBLING" ? "on" : ""}"><span class="dot">2</span>조립</div>
    </div>`;
  hright.innerHTML = `<button class="hbtn" id="btn-reset">↺ 새 작업</button>`;
  $("#recipe-select").onchange = (e) => post(`/api/recipe/${e.target.value}`);
  $("#btn-reset").onclick = () => post("/api/reset");
}
function renderHeaderPeriod() {
  const t = { diag: ["진단", "실시간 근거 · 시스템 상태"], history: ["이력", "대당 기록 · 전수 · 작업자 ID 없음"], analytics: ["분석", "품질 지표 · 레시피 전체"] }[S.view];
  hmid.innerHTML = `<div class="title" style="font-size:22px">${t[0]}</div><span style="color:#8FA3CE">${t[1]}</span>`;
  hright.innerHTML = `<div class="period">${[1, 7, 30].map((d) => `<button class="${S.period === d ? "on" : ""}" data-d="${d}">${d === 1 ? "오늘" : d + "일"}</button>`).join("")}</div>`;
  hright.querySelectorAll("button").forEach((b) => (b.onclick = () => { S.period = +b.dataset.d; route(); }));
}
function renderHeaderPlain(title, sub) { hmid.innerHTML = `<div class="title" style="font-size:22px">${title}</div><span style="color:#8FA3CE">${sub}</span>`; hright.innerHTML = ""; }

// ── 작업 탭 ─────────────────────────────────────────────────
function viewWork(p) {
  if (!p) return `<div class="empty">서버에 연결하는 중…</div>`;
  const mat = p.phase === "CHECK_MATERIALS";
  return `<div class="grid work">
    ${videoCard(p, false)}
    <div class="card">${mat ? tableMaterials(p) : tableHoles(p)}</div>
    ${verdictCard(p)}
  </div>`;
}
function videoCard(p, diag) {
  const [w, h] = p.frame_size || [1280, 720];
  const right = diag ? `<span class="note">${p.calibration_status === "UNVALIDATED_DEFAULTS" ? chip("hold", "ROI 미보정") : ""}${chip("wait", "오버레이 상세")}</span>`
                     : `<span class="note">H1 은 화면 왼쪽 · 파트는 위쪽</span>`;
  return `<div class="card video"><h3>실시간 영상 <span class="live">LIVE</span>${right}</h3>
    <div class="frame">${p.has_video ? `<img src="/video" alt="">` : `<span class="nocam">카메라 없음 — ${esc(p.recipe?.recipe_id || "")} 데모 소스, 오버레이만 표시</span>`}
    <canvas id="overlay" width="${w}" height="${h}"></canvas></div></div>`;
}
function tableMaterials(p) {
  const e = p.materials?.expected || {}, o = p.materials?.observed || {};
  const rows = CLASS_ORDER.map((c) => {
    const ex = e[c] ?? 0, ob = o[c] ?? 0;
    let cls = "ok", st = "준비됨";
    if (ob < ex) { cls = "wait"; st = `${ex - ob}개 더 놓기`; } else if (ob > ex) { cls = "ng"; st = ex ? `${ob - ex}개 치우기` : "여기 없음 — 치우기"; }
    return `<tr class="${cls}"><td>${NAME[c]}</td><td class="mono">${ex}</td><td class="mono ${cls === "ok" ? "" : "st"}">${ob}</td><td class="st">${st}</td></tr>`;
  }).join("");
  return `<h3>재료 확인 <span class="note">탁자 위에 딱 맞게 있어야 조립이 시작됩니다</span></h3>
    <table class="t"><tr><th>종류</th><th>필요</th><th>있음</th><th>상태</th></tr>${rows}</table>`;
}
function tableHoles(p) {
  const exp = {}; (p.recipe.placements || []).forEach((pl) => (exp[pl.mother_hole] = pl));
  const rings = S.rings || holeStates(p);
  const LAB = { ok: "맞음", ng: "틀림", wait: "아직", skip: "비움", hold: "보류", none: "" };
  const rows = [1, 2, 3, 4, 5].map((h) => {
    const st = rings[h], ex = exp[h], ob = observedAt(p, h);
    const seen = [ob.bolt, ob.part].filter(Boolean).map((c) => SHORT[c]).join(" + ");
    return `<tr class="${st}"><td>H${h}</td><td>${ex ? bolt(ex.bolt) + part(ex.part) : '<span style="color:var(--muted)">비워 둠</span>'}</td>
      <td class="now">${seen || "—"}</td><td class="st">${LAB[st] || ""}</td></tr>`;
  }).join("");
  return `<h3>자리별 현황 <span class="note">순서는 상관없습니다</span></h3>
    <table class="t"><tr><th>자리</th><th>꽂을 것</th><th>지금</th><th>상태</th></tr>${rows}</table>`;
}

function verdictCard(p) {
  const st = p.status, cand = p.candidate, mat = p.phase === "CHECK_MATERIALS";
  const stableChip = !p.stable && st !== "HOLD" ? `<span class="stable">${chip("muted", "확인 중 … 손을 떼고 잠시 기다리세요")}</span>` : "";
  let big = "", sub = "", body = "", hint = "", cls = st;
  if (st === "HOLD" || (cand.status === "HOLD" && !p.confirmed)) {
    cls = "HOLD";
    const code = (cand.issues || []).find((i) => HOLD_TEXT[i.code])?.code;
    const [t, d] = code ? HOLD_TEXT[code](p) : ["판단할 수 없습니다", "잠시 기다리세요."];
    big = "잠깐"; sub = mat ? "재료를 확인할 수 없습니다" : "Mother 를 바로 놓으세요";
    if (!code && mat) { big = "준비 중"; sub = "재료 확인을 시작합니다"; cls = "IN_PROGRESS"; }
    body = `<div class="reason"><div class="t">${esc(t)}</div><div class="d">${esc(d)}</div><div class="e">보류는 불량이 아닙니다. 아무것도 빼지 마세요.</div></div>`;
  } else if (mat) {
    const e = p.materials?.expected || {}, o = p.materials?.observed || {};
    const remove = CLASS_ORDER.filter((c) => (o[c] ?? 0) > (e[c] ?? 0)), add = CLASS_ORDER.filter((c) => (o[c] ?? 0) < (e[c] ?? 0));
    if (st === "NG") { cls = "NG"; big = "재료 NG"; sub = remove.length ? `${SHORT[remove[0]]} ${o[remove[0]] - (e[remove[0]] ?? 0)}개를 치우세요` : "재료가 맞지 않습니다"; }
    else if (st === "READY" || cand.status === "READY") { cls = "READY"; big = "준비 완료"; sub = "재료가 맞습니다 — 곧 조립으로 넘어갑니다"; }
    else { cls = "IN_PROGRESS"; big = "재료 준비"; sub = add.length ? `${SHORT[add[0]]} ${(e[add[0]] ?? 0) - (o[add[0]] ?? 0)}개 더 놓으세요` : "재료를 올려 주세요"; }
    body = (remove.length ? `<div class="label">치우기</div>${remove.map((c) => chip("ng", `${SHORT[c]}  × ${o[c] - (e[c] ?? 0)}`, "lg")).join("")}` : "")
         + (add.length ? `<div class="label">더 놓기</div>${add.map((c) => chip("wait", `${SHORT[c]}  × ${(e[c] ?? 0) - (o[c] ?? 0)}`, "lg")).join("")}` : "");
    hint = `딱 맞게 놓고 ${(p.timing.material_stable_ms / 1000).toFixed(1)}초 지나면 조립 단계로 자동으로 넘어갑니다.`;
  } else if (st === "PASS") {
    big = "PASS"; sub = `${p.recipe.recipe_id}  전부 맞음`;
    body = `<button class="bigbtn" id="btn-complete">작업 완료</button>`;
    hint = "누르면 기록되고 다음 제품의 재료 확인으로 넘어갑니다.<br>누르기 전까지는 계속 보고 있습니다 — 빼면 다시 '조립 중'이 됩니다.";
  } else if (st === "NG") {
    const issues = (cand.issues || []).filter((i) => !i.code.startsWith("MISSING"));
    if (issues.length) {
      const [first, rest] = primaryIssue(issues); const [t1] = human(first);
      big = "NG"; sub = t1;
      body = first.code.startsWith("WRONG")
        ? `<div class="compare"><div class="h">H${first.hole_id}</div><div><div class="cap">있어야 할 것</div>${chip("ok", SHORT[first.expected], "lg")}</div><div class="arrow">→</div><div><div class="cap">지금 있는 것</div>${chip("ng", SHORT[first.observed], "lg")}</div></div>`
        : `<div class="compare" style="grid-template-columns:70px 1fr"><div class="h">H${first.hole_id}</div><div><div class="cap">이 자리는 비워 둡니다</div>${chip("ng", (first.observed || "").split(",").map((c) => SHORT[c] || c).join(", "), "lg")}</div></div>`;
      if (rest.length) body += `<div class="label">그다음 · 외 ${rest.length}건</div>` + rest.map((i) => { const [a, b] = human(i); return `<div class="sec"><span class="t">${esc(a)}</span><span class="d">${esc(b)}</span></div>`; }).join("");
    } else { big = "NG"; sub = "확인 중"; }
    hint = "고치면 자동으로 다시 확인합니다. 누를 것 없습니다.";
  } else {  // IN_PROGRESS
    cls = "IN_PROGRESS"; big = "조립 중";
    const exp = p.recipe.placements || [], rings = S.rings || holeStates(p);
    const remain = exp.filter((pl) => rings[pl.mother_hole] !== "ok"), done = exp.length - remain.length;
    sub = `${done ? `${done}자리 맞음 · ` : ""}${remain.length}자리 남음`;
    body = `<div class="label">남은 자리</div>` + remain.map((pl) => `<div class="remain"><div class="h">H${pl.mother_hole}</div><div>${chip(pl.bolt === "bolt_1" ? "b1" : "b2", SHORT[pl.bolt], "lg")}${chip("part", SHORT[pl.part], "lg")}</div></div>`).join("");
    hint = `꽂고 손을 떼면 ${(p.timing.stable_ms / 1000).toFixed(1)}초 뒤 자동으로 확인합니다. 누를 것 없습니다.`;
  }
  setTimeout(() => { const b = $("#btn-complete"); if (b) b.onclick = async () => { b.disabled = true; const r = await post("/api/complete"); if (!r.ok) { alert(r.reason); b.disabled = false; } }; });
  return `<div class="card verdict ${cls}">${stableChip}<div class="big ${big.length > 4 ? "long" : ""}">${esc(big)}</div><div class="sub">${esc(sub)}</div><div class="body">${body}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</div>`;
}

// ── 영상 오버레이 (canvas) ────────────────────────────────────
const COL = { ok: "#15803D", ng: "#C81E1E", wait: "#4C8DFF", skip: "#8A94A3", hold: "#9A6B12", none: "#5C6674" };
function drawOverlay(p, diag) {
  const cv = $("#overlay"); if (!cv || !p) return;
  const ctx = cv.getContext("2d"); ctx.clearRect(0, 0, cv.width, cv.height);
  const g = p.geometry || {}, pose = g.pose;
  ctx.lineWidth = 3; ctx.font = "bold 34px sans-serif"; ctx.textAlign = "center";
  if (!p.has_video) { const order = { mother_part: 0, part_2hole: 1, part_3hole: 1 }; for (const d of [...(p.detections || [])].sort((a, b) => (order[a.class_name] ?? 2) - (order[b.class_name] ?? 2))) drawSynthetic(ctx, d); }   // 카메라 없음: 검출을 그림으로 대신 (볼트가 위)
  if (diag) for (const d of p.detections || []) drawObb(ctx, d, d.class_name === "mother_part" ? "#5FD38D" : d.class_name.startsWith("bolt") ? "#FFD166" : d.class_name === "part_2hole" ? "#7FE0FF" : "#FF9BD0", `${d.class_name} ${d.confidence.toFixed(2)}`);
  if (!pose) {  // HOLD 등 geometry 없음 — Mother 검출만 있으면 윤곽과 각도
    const m = (p.detections || []).filter((d) => d.class_name === "mother_part");
    if (m.length === 1 && !diag) drawObb(ctx, m[0], "#9A6B12", null, [10, 6]);
    const angleHold = (p.candidate.issues || []).some((i) => i.code === "MOTHER_ANGLE_OUT_OF_RANGE");
    if (m.length === 1 && p.mother_angle_deg != null && (diag || angleHold)) { ctx.fillStyle = "#FFD166"; ctx.fillText(`${p.mother_angle_deg.toFixed(1)}°`, m[0].center_xy[0], m[0].center_xy[1] - m[0].height / 2 - 60); }
    return;
  }
  // Mother 윤곽
  ctx.save(); ctx.translate(pose.center[0], pose.center[1]); ctx.rotate(pose.angle_rad);
  ctx.strokeStyle = "#5FD38D"; ctx.setLineDash([12, 8]); ctx.strokeRect(-pose.width / 2 - 10, -pose.height / 2 - 10, pose.width + 20, pose.height + 20); ctx.setLineDash([]);
  if (diag) { ctx.strokeStyle = "#7FB4FF"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(70, 0); ctx.moveTo(0, 0); ctx.lineTo(0, -90); ctx.stroke(); ctx.fillStyle = "#7FB4FF"; ctx.fillText("u", 84, 8); ctx.fillText("-v", 14, -96); ctx.lineWidth = 3; }
  ctx.restore();
  if (diag) {  // Bolt / Part ROI (코드가 계산한 polygon 그대로)
    ctx.lineWidth = 2;
    for (const [h, poly] of Object.entries(g.bolt_rois || {})) polygon(ctx, poly, "#FFD166");
    for (const [h, byCls] of Object.entries(g.part_rois || {})) { const pl = (p.recipe.placements || []).find((x) => String(x.mother_hole) === h); if (pl) polygon(ctx, byCls[pl.part], pl.part === "part_2hole" ? "#7FE0FF" : "#FF9BD0", [6, 5]); }
    ctx.lineWidth = 3;
  }
  const rings = S.rings || holeStates(p);
  for (const [h, pt] of Object.entries(g.holes || {})) {
    const st = rings[h] || "none", c = COL[st];
    ctx.strokeStyle = c; ctx.setLineDash(st === "wait" || st === "skip" ? [8, 7] : []); ctx.lineWidth = st === "ok" || st === "ng" ? 6 : 3;
    ctx.beginPath(); ctx.arc(pt[0], pt[1], 44, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = c; ctx.fillText(`H${h}`, pt[0], pt[1] + 96);
    if (st === "ok" || st === "ng" || st === "wait") { ctx.beginPath(); ctx.arc(pt[0] + 34, pt[1] - 34, 17, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "bold 24px sans-serif"; ctx.fillText(st === "ok" ? "✓" : st === "ng" ? "✕" : "!", pt[0] + 34, pt[1] - 25); ctx.font = "bold 34px sans-serif"; }
  }
}
function drawSynthetic(ctx, d) {   // 데모·JSONL 소스에서 영상 대신 보여 주는 합성 부품 그림
  const fill = { mother_part: "#DBC79E", part_2hole: "#DBC79E", part_3hole: "#DBC79E", bolt_1: "#F2C518", bolt_2: "#E7822A" }[d.class_name] || "#888";
  ctx.save(); ctx.translate(d.center_xy[0], d.center_xy[1]); ctx.rotate(d.angle_rad); ctx.fillStyle = fill; ctx.strokeStyle = "#B9A277"; ctx.lineWidth = 2;
  if (d.class_name.startsWith("bolt")) { ctx.beginPath(); ctx.arc(0, 0, d.width / 2.4, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = "#00000040"; ctx.beginPath(); ctx.arc(0, 0, d.width / 6, 0, Math.PI * 2); ctx.fill(); }
  else { ctx.beginPath(); ctx.roundRect(-d.width / 2, -d.height / 2, d.width, d.height, 8); ctx.fill(); ctx.stroke();
    const holes = d.class_name === "mother_part" ? 5 : d.class_name === "part_3hole" ? 3 : d.class_name === "part_2hole" ? 2 : 0;
    ctx.fillStyle = "#3A3228"; for (let k = 0; k < holes; k++) { const t = holes === 1 ? 0 : (k / (holes - 1) - 0.5) * (holes === 5 ? 0.8 : 0.7); ctx.beginPath(); ctx.arc(t * d.width, 0, Math.min(d.height, d.width) * 0.22, 0, Math.PI * 2); ctx.fill(); } }
  ctx.restore();
}
function drawObb(ctx, d, color, label, dash) {
  ctx.save(); ctx.translate(d.center_xy[0], d.center_xy[1]); ctx.rotate(d.angle_rad); ctx.strokeStyle = color; ctx.lineWidth = 2.5; if (dash) ctx.setLineDash(dash);
  ctx.strokeRect(-d.width / 2, -d.height / 2, d.width, d.height); ctx.restore();
  if (label) { ctx.font = "bold 26px monospace"; ctx.textAlign = "left"; const w = ctx.measureText(label).width + 14, x = d.center_xy[0] - d.width / 2, y = d.center_xy[1] - d.height / 2 - 36; ctx.fillStyle = color; ctx.fillRect(x, y, w, 34); ctx.fillStyle = "#fff"; ctx.fillText(label, x + 7, y + 26); ctx.textAlign = "center"; ctx.font = "bold 34px sans-serif"; }
}
function polygon(ctx, pts, color, dash) { if (!pts) return; ctx.strokeStyle = color; ctx.setLineDash(dash || []); ctx.beginPath(); pts.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]))); ctx.closePath(); ctx.stroke(); ctx.setLineDash([]); }

// ── 진단 탭 ─────────────────────────────────────────────────
function subtabs() { return `<div class="subtabs"><button class="${S.sub === "live" ? "on" : ""}" data-s="live">실시간</button><button class="${S.sub === "system" ? "on" : ""}" data-s="system">시스템 상태</button></div>`; }
function bindSubtabs() { /* 위임 방식 — main 이 다시 그려져도 살아 있다 */ }
main.addEventListener("click", (e) => { const b = e.target.closest(".subtabs button"); if (!b) return; S.sub = b.dataset.s; if (S.sub === "system") loadDiag(); else render(false); });
function viewDiagLive(p) {
  if (!p) return subtabs() + `<div class="empty">서버에 연결하는 중…</div>`;
  const [first] = primaryIssue((p.candidate.issues || []).filter((i) => !i.code.startsWith("MISSING")));
  const html = subtabs() + `<div class="grid diag">
    ${videoCard(p, true)}
    <div class="card"><h3>판정 내부</h3><div class="kv" id="kv-judge">${kvJudge(p, first)}</div>
      <div class="note" style="margin-top:14px">candidate.issues (evaluator.py 정렬 그대로)</div><div id="issues">${issuesHtml(p)}</div></div>
    <div class="card"><h3>프레임 · 파이프라인</h3><div class="kv" id="kv-frame">${kvFrame(p)}</div></div>
    <div class="card"><h3>상태 변경 이력 <span class="note">이 제품 · 변할 때만 · 최신이 위</span></h3><div id="events">${eventsHtml(p)}</div></div>
  </div>`;
  setTimeout(bindSubtabs); return html;
}
function updateDiagLive(p) { const a = $("#kv-frame"); if (a) a.innerHTML = kvFrame(p); const e = $("#events"); if (e) e.innerHTML = eventsHtml(p); }
const kv = (k, v, c = "") => `<div class="k">${k}</div><div class="v" style="color:${c}">${v}</div>`;
function kvJudge(p, first) {
  const c = { PASS: "var(--ok)", NG: "var(--ng)", HOLD: "var(--hold)", IN_PROGRESS: "var(--wait)", READY: "var(--ok)" };
  return kv("phase / evaluated_phase", `${p.phase} / ${p.evaluated_phase}`) + kv("status (표시)", p.status, c[p.status]) + kv("candidate", p.candidate.status, c[p.candidate.status])
    + kv("confirmed", p.confirmed ? `${p.confirmed.status}${p.confirmed.status === p.candidate.status ? "  (== candidate)" : ""}` : "None", p.confirmed && c[p.confirmed.status])
    + kv("stable", String(p.stable), p.stable ? "var(--ok)" : "var(--hold)") + kv("대표 오류 → 화면", first ? `${first.code} H${first.hole_id}  (정책: WRONG > UNEXPECTED > ORIENT > MISSING)` : "—");
}
function kvFrame(p) {
  const t = p.timing || {}, pose = p.geometry?.pose;
  return kv("frame_id / ts_ms", `${p.frame_id} / ${p.ts_ms}`) + kv("frame gap", t.gap_ms == null ? "—" : `${t.gap_ms} ms  (max ${t.max_frame_gap_ms})`, t.gap_ms > t.max_frame_gap_ms ? "var(--ng)" : "var(--ok)")
    + kv("core+store 처리 / fps", `${t.total_ms} ms / ${t.fps}`) + kv("mother pose", pose ? `(${pose.center[0].toFixed(0)}, ${pose.center[1].toFixed(0)}) · W ${pose.width.toFixed(0)} · H ${pose.height.toFixed(0)} · ${(pose.angle_rad * 180 / Math.PI).toFixed(1)}°` : (p.mother_angle_deg != null ? `geometry 없음 · 검출 각도 ${p.mother_angle_deg.toFixed(1)}°` : "geometry 없음"))
    + kv("stable / material", `${t.stable_ms} ms / ${t.material_stable_ms} ms`) + kv("calibration_status", p.calibration_status, p.calibration_status === "UNVALIDATED_DEFAULTS" ? "var(--hold)" : "var(--ok)")
    + kv("product_id / run_id", `${p.product_id} / ${p.run_id}`);
}
function issuesHtml(p) { const iss = p.candidate.issues || []; return iss.length ? iss.map((i) => `<div class="issue"><span class="c" style="color:${i.code.startsWith("MISSING") ? "var(--wait)" : (p.candidate.status === "HOLD" ? "var(--hold)" : "var(--ng)")}">${i.code}</span><span>${i.hole_id ? "H" + i.hole_id : "—"}</span><span>expected ${esc(i.expected)}</span><span>observed ${esc(i.observed)}</span></div>`).join("") : `<div class="note">issues 없음</div>`; }
function eventsHtml(p) {
  const c = { PASS: "var(--ok)", NG: "var(--ng)", HOLD: "var(--hold)", IN_PROGRESS: "var(--wait)", READY: "var(--ok)" };
  const ev = [...(p.events || [])].reverse();
  return ev.length ? ev.map((e) => `<div class="evrow"><span class="mono" style="color:var(--muted)">#${e.seq}</span><span>${e.evaluated_phase === "CHECK_MATERIALS" ? "재료" : "조립"}${e.event_type === "ASSEMBLY_STARTED" ? "→조립" : ""}</span><span class="st" style="color:${e.event_type === "ASSEMBLY_STARTED" ? "var(--blue)" : c[e.status]}">${e.event_type === "ASSEMBLY_STARTED" ? "ASSEMBLY_STARTED" : e.status}</span><span>${(e.issues || []).map((i) => i.code + (i.hole_id ? ":H" + i.hole_id : "")).join(" · ") || "—"}</span></div>`).join("") : `<div class="note">아직 없음</div>`;
}
async function loadDiag() { S.diag = await api(`/api/diagnostics?days=${S.period}&hours=1`); main.innerHTML = viewDiagSystem(S.diag); bindSubtabs(); }
function viewDiagSystem(d) {
  const m = d.metrics || [], last = m[m.length - 1];
  const fps = m.length ? (m.reduce((a, r) => a + r.fps, 0) / m.length).toFixed(1) : "—";
  const p95 = m.length ? Math.max(...m.map((r) => r.total_ms_p95 || 0)).toFixed(0) : "—";
  const holdPct = m.length ? (100 * m.reduce((a, r) => a + r.hold_frames, 0) / Math.max(1, m.reduce((a, r) => a + r.frames, 0))).toFixed(1) : "—";
  const gapOver = m.reduce((a, r) => a + r.frame_gap_over, 0);
  const holds = d.hold_reasons || [];
  const conf = Object.entries(d.confidence || {});
  const cfg = d.config || {};
  return subtabs() + `<div class="grid analytics">
    <div class="kpis">${tile("처리 FPS (평균)", fps, "목표 ≥ 10")}${tile("처리 지연 p95 (최근 1시간 최대)", `${p95} ms`, `frame gap 한계 ${cfg.max_frame_gap_ms} ms`)}${tile("보류 프레임 비율", `${holdPct}%`, "카메라·자세 문제 지표")}${tile("프레임 끊김", `${gapOver}회`, `${cfg.max_frame_gap_ms} ms 초과`)}${tile("ROI 보정", cfg.calibration_status === "UNVALIDATED_DEFAULTS" ? "미보정" : "보정됨", cfg.calibration_status, cfg.calibration_status === "UNVALIDATED_DEFAULTS" ? "bad" : "")}</div>
    <div class="card"><h3>처리 지연 — 분 단위 p95 <span class="note">ms · core+store · 추론 시간은 카메라 소스가 붙으면 포함</span></h3>${m.length ? lineChart(m.map((r) => r.total_ms_p95 || 0), m.map((r) => r.bucket_utc.slice(11, 16)), "ms") : '<div class="empty">아직 metrics 버킷이 없습니다 (1분 뒤)</div>'}</div>
    <div class="card"><h3>보류(HOLD) 원인 <span class="note">${S.period}일</span></h3>${holds.length ? hbars(holds.map((r) => [r.code, r.n]), "건") : '<div class="empty">없음</div>'}</div>
    <div class="card"><h3>클래스별 confidence — 중앙값과 p10~p90 <span class="note">판정에 쓰인 검출만 · 임계 ${cfg.confidence_threshold}</span></h3>${conf.length ? rangeChart(conf, cfg.confidence_threshold) : '<div class="empty">없음</div>'}</div>
    <div class="card"><h3>모델 · 설정 <span class="note">mvp.json 그대로 · run ${d.run_id}</span></h3><div class="kv">${["confidence_threshold", "max_mother_angle_deg", "stable_duration_ms", "material_stable_duration_ms", "max_frame_gap_ms", "part_overlap_threshold", "part_max_angle_deg", "calibration_status"].map((k) => kv(k, esc(cfg[k]), k === "calibration_status" && cfg[k] === "UNVALIDATED_DEFAULTS" ? "var(--hold)" : "")).join("")}</div></div>
  </div>`;
}

// ── 이력 탭 ─────────────────────────────────────────────────
async function loadHistory() {
  const qs = new URLSearchParams({ limit: 100 }); const f = S.hf || {};
  if (f.recipe) qs.set("recipe_id", f.recipe); if (f.result) qs.set("result", f.result); if (f.ng) qs.set("ng_only", "1"); if (f.hold) qs.set("hold_only", "1");
  S.hist = await api(`/api/history?${qs}`);
  if (S.sel == null && S.hist.length) S.sel = S.hist[0].product_id;
  S.tl = S.sel != null ? await api(`/api/timeline/${S.sel}`) : [];
  if (S.view === "history") main.innerHTML = viewHistory();
}
function viewHistory() {
  if (!S.hist) return `<div class="empty">불러오는 중…</div>`;
  const f = S.hf || {};
  const rows = S.hist.map((r) => `<tr class="click ${r.product_id === S.sel ? "sel" : ""}" data-id="${r.product_id}">
    <td class="mono">${(r.closed_utc || "").slice(11)}</td><td>P-${String(r.product_id).padStart(4, "0")}</td><td class="mono">${r.recipe_id}</td>
    <td>${r.cycle_ms != null ? (r.cycle_ms / 1000).toFixed(0) + "초" : "—"}</td><td style="color:var(--muted)">${r.materials_ms != null ? (r.materials_ms / 1000).toFixed(0) + "초" : "—"}</td><td style="color:var(--muted)">${r.assembly_ms != null ? (r.assembly_ms / 1000).toFixed(0) + "초" : "—"}</td>
    <td style="color:${r.ng_count ? "var(--ng)" : "var(--muted)"};font-weight:700">${r.ng_count + r.material_ng_count}</td><td style="color:${r.hold_count ? "var(--hold)" : "var(--muted)"};font-weight:700">${r.hold_count}</td>
    <td style="color:${r.first_pass ? "var(--ok)" : "var(--ng)"}">${r.first_pass ? "○" : "✕"}</td><td class="st" style="color:${r.result === "COMPLETED" ? "var(--ok)" : "var(--hold)"}">${r.result === "COMPLETED" ? "완료" : "중단"}</td></tr>`).join("");
  const html = `<div class="grid history">
    <div class="card"><h3>제품별 기록 <span class="note">UTC 시각 · 클릭하면 오른쪽에 타임라인</span></h3>
      <div class="filters"><select id="f-recipe"><option value="">레시피 전체</option>${["recipe_1", "recipe_2", "recipe_3"].map((r) => `<option ${f.recipe === r ? "selected" : ""}>${r}</option>`).join("")}</select>
        <select id="f-result"><option value="">결과 전체</option><option value="COMPLETED" ${f.result === "COMPLETED" ? "selected" : ""}>완료</option><option value="ABANDONED" ${f.result === "ABANDONED" ? "selected" : ""}>중단</option></select>
        <label><input type="checkbox" id="f-ng" ${f.ng ? "checked" : ""}> NG 있음만</label><label><input type="checkbox" id="f-hold" ${f.hold ? "checked" : ""}> 보류 있음만</label></div>
      ${S.hist.length ? `<table class="t"><tr><th>완료 시각</th><th>제품</th><th>레시피</th><th>사이클</th><th>재료</th><th>조립</th><th>NG</th><th>보류</th><th>첫 시도</th><th>결과</th></tr>${rows}</table>` : '<div class="empty">아직 완료된 제품이 없습니다. 작업 탭에서 [작업 완료] 를 누르면 여기 쌓입니다.</div>'}
      <div class="note">첫 시도 = NG 이벤트 0건으로 완료 · 중단 = 새 작업으로 리셋됨</div></div>
    <div class="card"><h3>${S.sel != null ? `P-${String(S.sel).padStart(4, "0")} · 타임라인` : "타임라인"} <span class="note">events 그대로</span></h3>${timelineHtml(S.tl || [])}</div>
  </div>`;
  setTimeout(() => {
    document.querySelectorAll("tr.click").forEach((tr) => (tr.onclick = () => { S.sel = +tr.dataset.id; loadHistory(); }));
    const upd = () => { S.hf = { recipe: $("#f-recipe").value, result: $("#f-result").value, ng: $("#f-ng").checked, hold: $("#f-hold").checked }; loadHistory(); };
    ["#f-recipe", "#f-result", "#f-ng", "#f-hold"].forEach((s) => ($(s).onchange = upd));
  });
  return html;
}
function timelineHtml(tl) {
  const c = { PASS: "var(--ok)", NG: "var(--ng)", HOLD: "var(--hold)", IN_PROGRESS: "var(--wait)", READY: "var(--ok)" };
  if (!tl.length) return '<div class="empty">제품을 선택하세요</div>';
  const t0 = tl[0].ts_ms;
  return `<div class="tl">${tl.map((e) => {
    const isStart = e.event_type === "ASSEMBLY_STARTED", isEnd = e.event_type.startsWith("PRODUCT_");
    const col = isStart ? "var(--blue)" : isEnd ? "var(--navy)" : c[e.status];
    const label = isStart ? "ASSEMBLY_STARTED" : isEnd ? e.event_type : e.status;
    const note = isStart ? "재료 확인 완료 → 조립 시작" : isEnd ? (e.event_type === "PRODUCT_COMPLETED" ? "작업 완료 버튼 → 기록 · reset" : "새 작업 → 중단") : ((e.issues || []).map((i) => human(i)[0] + (i.code.startsWith("MATERIAL") ? ` (${i.expected} → ${i.observed})` : "")).join(" · ") || (e.status === "PASS" ? "전부 일치" : ""));
    return `<div class="item" style="--c:${col}"><span class="t">+${((e.ts_ms - t0) / 1000).toFixed(1)}s</span><span class="s">${label}</span>${e.mother_angle_deg != null && e.status === "HOLD" ? `<span class="t"> ${e.mother_angle_deg.toFixed(0)}°</span>` : ""}<div class="n">${esc(note)}</div></div>`;
  }).join("")}</div>`;
}

// ── 분석 탭 ─────────────────────────────────────────────────
async function loadAnalytics() { S.ana = await api(`/api/analytics?days=${S.period}`); S.hist = await api("/api/history?limit=500"); if (S.view === "analytics") main.innerHTML = viewAnalytics(); }
function tile(l, v, d, cls = "") { return `<div class="tile"><div class="l">${l}</div><div class="v">${v}</div><div class="d ${cls}">${d}</div></div>`; }
function viewAnalytics() {
  const a = S.ana; if (!a) return `<div class="empty">불러오는 중…</div>`;
  const n = a.fpy.total?.n || 0, fpy = a.fpy.total?.fpy, ng = (a.pareto || []).reduce((s, r) => s + r.n, 0);
  const holdProducts = (S.hist || []).filter((r) => r.result === "COMPLETED"), holdPct = holdProducts.length ? (100 * holdProducts.filter((r) => r.hold_count > 0).length / holdProducts.length).toFixed(0) : "—";
  const rec = a.recovery || {};
  const cyc = Object.entries(a.cycle || {});
  const heat = a.heatmap || {};
  return `<div class="grid analytics">
    <div class="kpis">${tile("완료", `${n}대`, `${S.period}일 · 작업 완료 버튼 기준`)}${tile("첫 시도 통과율", fpy != null ? `${fpy}%` : "—", "NG 없이 완료한 비율")}${tile("조립 NG", `${ng}건`, "확정 이벤트 기준", ng ? "bad" : "")}${tile("NG → 복구 중앙값", rec.median_ms != null ? `${(rec.median_ms / 1000).toFixed(1)}초` : "—", rec.p90_ms != null ? `p90 ${(rec.p90_ms / 1000).toFixed(1)}초` : "")}${tile("보류 있던 제품", holdPct === "—" ? "—" : `${holdPct}%`, "카메라·자세 문제 지표", "warn")}</div>
    <div class="card"><h3>NG 유형 — 무엇이 가장 자주 틀리나 <span class="note">조립 단계 · ${ng}건</span></h3>${a.pareto?.length ? hbars(a.pareto.map((r) => [r.code, r.n, `누적 ${r.cum_pct}%`]), "건") : '<div class="empty">아직 NG 가 없습니다</div>'}</div>
    <div class="card"><h3>자리 × 레시피 — 어디서 틀리나 <span class="note">NG 건수 · 진할수록 많음</span></h3>${Object.keys(heat).length ? heatmap(heat) : '<div class="empty">아직 데이터가 없습니다</div>'}</div>
    <div class="card"><h3>첫 시도 통과율 추이 <span class="note">일별 · 목표 90%</span></h3>${a.fpy_daily?.length > 1 ? lineChart(a.fpy_daily.map((r) => r.fpy), a.fpy_daily.map((r) => r.day.slice(5)), "%", 90, [0, 100]) : `<div class="empty">${a.fpy_daily?.length === 1 ? `${a.fpy_daily[0].day}: ${a.fpy_daily[0].fpy}% (${a.fpy_daily[0].n}대) — 이틀째부터 선이 그려집니다` : "아직 데이터가 없습니다"}</div>`}</div>
    <div class="card"><h3>사이클 타임 — 레시피별 중앙값 <span class="note">초 · 재료 확인 + 조립 · p90 표시</span></h3>${cyc.length ? stackChart(cyc) : '<div class="empty">아직 데이터가 없습니다</div>'}</div>
  </div>`;
}

// ── 레시피 탭 ───────────────────────────────────────────────
async function loadRecipes() { S.recipes = await api("/api/recipes"); if (S.view === "recipe") main.innerHTML = viewRecipe(); }
function viewRecipe() {
  const r = S.recipes; if (!r) return `<div class="empty">불러오는 중…</div>`;
  const stats = {}; (S.hist || []).forEach((h) => { if (h.result !== "COMPLETED") return; const s = (stats[h.recipe_id] ||= { n: 0, fp: 0, cyc: [] }); s.n++; s.fp += h.first_pass; s.cyc.push(h.cycle_ms); });
  const html = `<div class="grid recipe">${r.recipes.map((rc) => {
    const pl = {}; rc.placements.forEach((p) => (pl[p.mother_hole] = p));
    const need = { mother_part: 1 }; rc.placements.forEach((p) => { need[p.bolt] = (need[p.bolt] || 0) + 1; need[p.part] = (need[p.part] || 0) + 1; });
    const s = stats[rc.recipe_id], med = s?.cyc.length ? [...s.cyc].sort((a, b) => a - b)[Math.floor(s.cyc.length / 2)] : null;
    const on = rc.recipe_id === r.current;
    return `<div class="card rcard"><h3 class="mono">${rc.recipe_id}<span class="note">${on ? chip("ok", "사용 중") : ""}</span></h3>
      <div class="art">${recipeArt(pl)}</div>
      <div class="spec">${[1, 2, 3, 4, 5].map((h) => `<b>H${h}</b><span>${pl[h] ? bolt(pl[h].bolt) + part(pl[h].part) : '<span style="color:var(--muted)">비워 둠 — 무엇이든 꽂히면 NG</span>'}</span><span class="code">${pl[h] ? pl[h].bolt + " · " + pl[h].part : ""}</span>`).join("")}</div>
      <div class="note">재료 확인에서 세는 수량: ${Object.entries(need).map(([c, n]) => `${SHORT[c]}×${n}`).join(" · ")}</div>
      <div class="stats"><div><div class="l">${S.period}일 완료</div><div class="v">${s ? s.n + "대" : "—"}</div></div><div><div class="l">첫 시도 통과</div><div class="v">${s ? (100 * s.fp / s.n).toFixed(1) + "%" : "—"}</div></div><div><div class="l">중앙 사이클</div><div class="v">${med != null ? (med / 1000).toFixed(0) + "초" : "—"}</div></div></div>
      <button class="use ${on ? "on" : ""}" data-r="${rc.recipe_id}" ${on ? "disabled" : ""}>${on ? "사용 중" : "이 레시피로 새 작업"}</button></div>`;
  }).join("")}
  <div class="card" style="grid-column:1/-1"><h3>레시피가 바뀌면</h3><div style="line-height:1.9">
    · 파일만 고치면 됩니다. 모델·코드는 그대로 — 판정은 레시피 테이블과 대조해서 나옵니다 (NFR-008).<br>
    · 규칙: H1~H4 만 지정할 수 있고 H5 는 항상 비움 (recipe.py 검증). 같은 Hole 을 두 번 쓸 수 없습니다.<br>
    · 재료 확인 수량은 자동 계산 — Mother 1 + 배치의 볼트·파트 합 (materials.py).<br>
    · 새 레시피를 넣으면 이 탭에 카드가 하나 늘고, 분석 탭의 자리별 표에 행이 하나 늘어납니다.</div></div></div>`;
  setTimeout(() => document.querySelectorAll(".rcard .use:not(.on)").forEach((b) => (b.onclick = async () => { await post(`/api/recipe/${b.dataset.r}`); location.hash = "#work"; })));
  return html;
}
function recipeArt(pl) {
  const W = 600, bw = 440, bh = 44, cx = 300, cy = 150;
  let s = `<svg viewBox="0 0 ${W} 200"><rect x="${cx - bw / 2}" y="${cy - bh / 2}" width="${bw}" height="${bh}" rx="6" fill="#DBC79E" stroke="#B9A277" stroke-width="2"/>`;
  [-0.4, -0.2, 0, 0.2, 0.4].forEach((a, i) => {
    const hx = cx + a * bw, h = i + 1, p = pl[h];
    if (p) { const holes = p.part === "part_2hole" ? 2 : 3, gap = 34, pad = 18, ph = gap * (holes - 1) + pad * 2;
      s += `<rect x="${hx - 20}" y="${cy + pad - ph}" width="40" height="${ph}" rx="5" fill="#DBC79E" stroke="#B9A277" stroke-width="2"/>`;
      for (let k = 0; k < holes; k++) s += `<circle cx="${hx}" cy="${cy - k * gap}" r="9" fill="#3A3228"/>`;
      s += `<circle cx="${hx}" cy="${cy}" r="12" fill="${p.bolt === "bolt_1" ? "#F2C518" : "#E7822A"}" stroke="#00000040" stroke-width="2"/>`; }
    else s += `<circle cx="${hx}" cy="${cy}" r="12" fill="#3A3228"/>`;
    s += `<text x="${hx}" y="${cy + 42}" text-anchor="middle" font-size="14" font-weight="${p ? 700 : 400}" fill="${p ? "#fff" : "#8A94A6"}">H${h}</text>`;
  });
  return s + `</svg>`;
}

// ── 차트 (SVG, 단일 색 램프) ─────────────────────────────────
const B = ["#D6E2FA", "#B9CDF5", "#93B0EE", "#6C8CE0", "#3060D8", "#1B3C8C"];
function hbars(rows, unit) {
  const W = 800, lw = 260, th = 22, gap = 16, mx = Math.max(...rows.map((r) => r[1])), pw = W - lw - 180;
  const H = rows.length * (th + gap);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${rows.map(([l, v, extra], i) => { const y = i * (th + gap), w = Math.max(4, (v / mx) * pw);
    return `<text x="${lw - 12}" y="${y + th - 5}" text-anchor="end" font-size="14" font-family="monospace" fill="#14161A">${esc(l)}</text><path d="M ${lw} ${y} H ${lw + w - 4} a 4 4 0 0 1 4 4 V ${y + th - 4} a 4 4 0 0 1 -4 4 H ${lw} Z" fill="${i ? B[2] : B[4]}"/><text x="${lw + w + 10}" y="${y + th - 5}" font-size="14" font-weight="700" fill="#14161A">${v}${unit}</text>${extra ? `<text x="${W}" y="${y + th - 5}" text-anchor="end" font-size="13" fill="#6B7480">${esc(extra)}</text>` : ""}`; }).join("")}</svg>`;
}
function heatmap(heat) {
  const rows = Object.keys(heat).sort(), cw = 110, ch = 56, gap = 4, mx = Math.max(1, ...rows.flatMap((r) => Object.values(heat[r])));
  const W = 110 + 5 * (cw + gap), H = 30 + rows.length * (ch + gap);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${[1, 2, 3, 4, 5].map((h, j) => `<text x="${110 + j * (cw + gap) + cw / 2}" y="18" text-anchor="middle" font-size="13" font-weight="700" fill="#6B7480">H${h}</text>`).join("")}
    ${rows.map((r, i) => { const y = 30 + i * (ch + gap); return `<text x="98" y="${y + ch / 2 + 5}" text-anchor="end" font-size="13" font-family="monospace">${r}</text>` + [1, 2, 3, 4, 5].map((h, j) => { const v = heat[r][h] ?? heat[r][String(h)] ?? 0, k = v === 0 ? 0 : Math.min(5, 1 + Math.floor((v / mx) * 4.999)); return `<rect x="${110 + j * (cw + gap)}" y="${y}" width="${cw}" height="${ch}" rx="4" fill="${B[k]}"/><text x="${110 + j * (cw + gap) + cw / 2}" y="${y + ch / 2 + 6}" text-anchor="middle" font-size="16" font-weight="${v === mx ? 700 : 400}" fill="${k >= 4 ? "#fff" : "#14161A"}">${v}</text>`; }).join(""); }).join("")}</svg>`;
}
function lineChart(series, labels, unit, ref, range) {
  const W = 800, H = 260, x0 = 60, y0 = 20, pw = W - x0 - 90, ph = H - y0 - 40;
  const lo = range ? range[0] : 0, hi = range ? range[1] : Math.max(10, Math.ceil(Math.max(...series) * 1.15));
  const X = (i) => x0 + (series.length > 1 ? (i * pw) / (series.length - 1) : pw / 2), Y = (v) => y0 + ph - ((v - lo) / (hi - lo)) * ph;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
  for (let k = 0; k < 4; k++) { const v = hi - ((hi - lo) * k) / 3, y = y0 + (ph * k) / 3; s += `<line x1="${x0}" y1="${y}" x2="${x0 + pw}" y2="${y}" stroke="#E6EAF0"/><text x="${x0 - 8}" y="${y + 4}" text-anchor="end" font-size="12" fill="#6B7480">${v.toFixed(0)}${unit}</text>`; }
  if (ref != null) s += `<line x1="${x0}" y1="${Y(ref)}" x2="${x0 + pw}" y2="${Y(ref)}" stroke="#9A6B12" stroke-width="1.5" stroke-dasharray="6 5"/><text x="${x0 + 6}" y="${Y(ref) - 6}" font-size="12" fill="#9A6B12" font-weight="700">목표 ${ref}${unit}</text>`;
  s += `<path d="M ${series.map((v, i) => `${X(i)} ${Y(v)}`).join(" L ")}" fill="none" stroke="${B[4]}" stroke-width="2" stroke-linejoin="round"/>`;
  series.forEach((v, i) => { s += `<circle cx="${X(i)}" cy="${Y(v)}" r="4.5" fill="${B[4]}" stroke="#fff" stroke-width="2"/>`; if (labels[i] && (series.length <= 12 || i % Math.ceil(series.length / 12) === 0)) s += `<text x="${X(i)}" y="${H - 14}" text-anchor="middle" font-size="12" fill="#6B7480">${esc(labels[i])}</text>`; });
  s += `<text x="${X(series.length - 1) + 10}" y="${Y(series[series.length - 1]) + 5}" font-size="14" font-weight="700">${series[series.length - 1]}${unit}</text>`;
  return s + `</svg>`;
}
function stackChart(entries) {
  const W = 800, H = 280, x0 = 60, y0 = 40, pw = W - x0 - 40, ph = H - y0 - 50;
  const mx = Math.max(10, ...entries.map(([, d]) => (d.cycle?.p90 || 0) / 1000)) * 1.1;
  const slot = pw / entries.length, bw = 24;
  let s = `<div class="legend"><span><i style="background:${B[1]}"></i>재료 확인</span><span><i style="background:${B[4]}"></i>조립</span><span><i style="background:#14161A;height:2px;vertical-align:3px"></i>p90</span></div><svg class="chart" viewBox="0 0 ${W} ${H}">`;
  for (let k = 0; k < 4; k++) { const v = mx - (mx * k) / 3, y = y0 + (ph * k) / 3; s += `<line x1="${x0}" y1="${y}" x2="${x0 + pw}" y2="${y}" stroke="#E6EAF0"/><text x="${x0 - 8}" y="${y + 4}" text-anchor="end" font-size="12" fill="#6B7480">${v.toFixed(0)}</text>`; }
  entries.forEach(([rid, d], i) => {
    const cx = x0 + slot * i + slot / 2 - bw / 2, mat = (d.materials?.median || 0) / 1000, asm = (d.assembly?.median || 0) / 1000, p90 = (d.cycle?.p90 || 0) / 1000;
    const hm = (mat / mx) * ph, ha = (asm / mx) * ph, base = y0 + ph;
    s += `<rect x="${cx}" y="${base - hm}" width="${bw}" height="${hm}" fill="${B[1]}"/><path d="M ${cx} ${base - hm - 2} V ${base - hm - 2 - ha + 4} a 4 4 0 0 1 4 -4 H ${cx + bw - 4} a 4 4 0 0 1 4 4 V ${base - hm - 2} Z" fill="${B[4]}"/>`;
    s += `<text x="${cx + bw / 2}" y="${base - hm - ha - 10}" text-anchor="middle" font-size="14" font-weight="700">${(mat + asm).toFixed(0)}초</text>`;
    if (p90) s += `<line x1="${cx - 10}" y1="${base - (p90 / mx) * ph}" x2="${cx + bw + 10}" y2="${base - (p90 / mx) * ph}" stroke="#14161A" stroke-width="2"/><text x="${cx + bw + 14}" y="${base - (p90 / mx) * ph + 4}" font-size="12" fill="#6B7480">p90 ${p90.toFixed(0)}</text>`;
    s += `<text x="${cx + bw / 2}" y="${H - 18}" text-anchor="middle" font-size="13" font-family="monospace" fill="#6B7480">${rid}</text>`;
  });
  return s + `</svg>`;
}
function rangeChart(conf, thr) {
  const W = 800, lw = 160, pw = W - lw - 120, rh = 44, H = conf.length * rh + 40;
  const X = (v) => lw + v * pw;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
  [0, 0.25, 0.5, 0.75, 1].forEach((v) => (s += `<line x1="${X(v)}" y1="10" x2="${X(v)}" y2="${H - 30}" stroke="#E6EAF0"/><text x="${X(v)}" y="${H - 12}" text-anchor="middle" font-size="12" fill="#6B7480">${v.toFixed(2)}</text>`));
  s += `<line x1="${X(thr)}" y1="6" x2="${X(thr)}" y2="${H - 30}" stroke="#9A6B12" stroke-width="1.5" stroke-dasharray="6 5"/>`;
  conf.forEach(([cls, d], i) => { const y = 30 + i * rh, warn = d.p10 < thr; s += `<text x="${lw - 12}" y="${y + 5}" text-anchor="end" font-size="14" font-family="monospace">${cls}</text><line x1="${X(d.p10)}" y1="${y}" x2="${X(d.p90)}" y2="${y}" stroke="${warn ? "#C81E1E" : B[2]}" stroke-width="6" stroke-linecap="round"/><circle cx="${X(d.median)}" cy="${y}" r="7" fill="${warn ? "#C81E1E" : B[4]}" stroke="#fff" stroke-width="2"/><text x="${X(d.p90) + 12}" y="${y + 5}" font-size="13" font-weight="700">${d.median.toFixed(2)}${warn ? " · p10 < 임계" : ""}</text>`; });
  return s + `</svg>`;
}

// ── 시계 · 시작 ─────────────────────────────────────────────
setInterval(() => ($("#clock").textContent = new Date().toTimeString().slice(0, 5)), 1000);
setInterval(() => { if (S.view === "history") loadHistory(); if (S.view === "analytics") loadAnalytics(); if (S.view === "diag" && S.sub === "system") loadDiag(); }, 5000);
route(); connect();
})();
