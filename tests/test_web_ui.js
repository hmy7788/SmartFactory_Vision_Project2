/* 작업 화면(web/static/app.js) 의 파생 상태 검사 — 브라우저 없이 node 로 payload 순서를 넣어 본다.
   실행:  node tests/test_web_ui.js      (tests/test_web.py 의 UiLogicTests 가 같은 것을 부른다)
   검사하는 것: 프레임마다 흔들리는 후보·수량이 화면을 흔들지 않는지 (확정만 그림 · 재료 수량 최빈값 · HOLD 유예 · 칩 지연). */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

// ── 최소 DOM 흉내 ──
// 조각마다 다시 그린 횟수를 센다: main(뼈대 — 영상 <img> 가 새로 열림) · table(자리/재료 표) · verdict(판정 카드)
const renders = { main: 0, table: 0, verdict: 0 };
function el(name) {
  const e = { _html: "", className: "", classList: { add() {}, remove() {}, toggle() {} }, style: {}, textContent: "", title: "", dataset: {},
              querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, getContext: () => null };
  const set = (v) => { e._html = v; if (name) renders[name]++; };
  Object.defineProperty(e, "innerHTML", { get: () => e._html, set });
  Object.defineProperty(e, "outerHTML", { get: () => e._html, set });
  return e;
}
const main = el("main"), table = el("table"), verdict = el("verdict"), note = el(), hmid = el(), hright = el(), misc = el();
const NULL_IDS = new Set(["#overlay", "#prog", "#hold-t", "#btn-complete"]);
const IDS = { "#main": main, "#header-mid": hmid, "#header-right": hright, "#table-card": table, "#verdict": verdict, "#video-note": note };
const document = { querySelector: (s) => IDS[s] || (NULL_IDS.has(s) ? null : misc), querySelectorAll: () => [] };
const window = { addEventListener() {} };
const sandbox = { window, document, location: { hash: "#work", protocol: "http:", host: "x" }, WebSocket: class { constructor() {} },
                  setInterval: () => 0, clearInterval() {}, setTimeout: (f) => { try { f(); } catch (_) {} return 0; }, fetch: () => Promise.reject(new Error("no server")),
                  JSON, Math, Date, Map, Set, Object, Array, String, Number, console, alert() {} };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "web", "static", "app.js"), "utf8"), sandbox, { filename: "app.js" });
const PK = window.__pokayoke, S = PK.S, UI = PK.UI;

// ── payload 조립 ──
const RECIPE = { recipe_id: "recipe_1", placements: [{ mother_hole: 1, bolt: "bolt_1", part: "part_2hole" }, { mother_hole: 3, bolt: "bolt_2", part: "part_3hole" }] };
const EXPECTED = { mother_part: 1, bolt_1: 1, bolt_2: 1, part_2hole: 1, part_3hole: 1 };
const TIMING = { stable_ms: 400, material_stable_ms: 1000, max_angle_deg: 15, max_frame_gap_ms: 500, gap_ms: 40, total_ms: 5, fps: 25 };
let ts = 1000, product = 1;
function pay(o) {
  ts += o.dt ?? 40;
  const cand = o.candidate || { status: "IN_PROGRESS", issues: [] };
  return Object.assign({
    type: "snapshot", frame_id: ts, ts_ms: ts, frame_size: [1280, 720], has_video: true, recipe: RECIPE, recipes: ["recipe_1"], run_id: 1, product_id: product,
    phase: "ASSEMBLING", evaluated_phase: "ASSEMBLING", status: o.confirmed ? o.confirmed.status : "HOLD", stable: o.stable ?? false,
    candidate: cand, confirmed: o.confirmed || null, materials: { expected: EXPECTED, observed: o.observed || {} }, observed: {},
    geometry: o.geometry ?? (cand.status === "HOLD" ? {} : { pose: { center: [640, 360], u: [1, 0], v: [0, 1], width: 800, height: 80, angle_rad: 0 }, holes: { 1: [300, 360], 3: [640, 360] } }),
    detections: [], mother_angle_deg: 0, calibration_status: "OK", source_error: null, video_at_end: false, timing: TIMING, events: [],
  }, o.extra || {});
}
const feed = (o) => { const p = pay(o); PK.onPayload(p); return p; };
const html = () => [main._html, note._html, table._html, verdict._html].join("\n"), text = () => html().replace(/<[^>]+>/g, " ");
const nRenders = () => renders.table + renders.verdict + renders.main;
let failed = 0, passed = 0;
function check(name, cond, detail = "") { if (cond) passed++; else { failed++; console.log(`FAIL  ${name}  ${detail}`); } }
function scenario(name, fn) { ts += 5000; product++; renders.main = renders.table = renders.verdict = 0; const f0 = failed; fn(); console.log(`  ${name}: ${failed === f0 ? "ok" : "FAILED"}`); }
const MISSING = (h, part, bolt) => [{ code: "MISSING_BOLT", hole_id: h, expected: bolt, observed: "" }, { code: "MISSING_PART", hole_id: h, expected: part, observed: "" }];
const IN_PROGRESS = { status: "IN_PROGRESS", issues: [...MISSING(1, "part_2hole", "bolt_1"), ...MISSING(3, "part_3hole", "bolt_2")] };
const NG = { status: "NG", issues: [{ code: "WRONG_BOLT", hole_id: 1, expected: "bolt_1", observed: "bolt_2" }, ...MISSING(3, "part_3hole", "bolt_2")] };
const HOLD = { status: "HOLD", issues: [{ code: "MOTHER_NOT_FOUND", hole_id: 0, expected: "", observed: "" }] };
const PASS = { status: "PASS", issues: [] };

// 1. 재료 수량이 프레임마다 흔들려도 표·카드는 최빈값으로 조용하다
scenario("materials counts are smoothed", () => {
  const good = { mother_part: 1, bolt_1: 1, bolt_2: 1, part_2hole: 1, part_3hole: 0 }, flick = { mother_part: 1, bolt_1: 0, bolt_2: 1, part_2hole: 2, part_3hole: 0 };
  for (let i = 0; i < 30; i++) feed({ phase: "CHECK_MATERIALS", extra: { phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" }, observed: i % 3 === 2 ? flick : good,
                                     candidate: { status: "IN_PROGRESS", issues: [] } });
  check("matView is the majority", S.matView.bolt_1 === 1 && S.matView.part_2hole === 1, JSON.stringify(S.matView));
  check("card names the missing part from the smoothed counts", text().includes("3구 파트 1개 더 놓으세요"), text().slice(0, 300));
  check("few re-renders despite flicker", renders.table + renders.verdict <= 4 && renders.main <= 1, JSON.stringify(renders));
  check("no chip in materials phase", !html().includes("확인 중"));
});

// 2. 재료가 딱 맞으면 '준비 완료' + 진행 막대 (핵심 후보 READY 가 이어지는 동안 차오른다)
scenario("ready shows a progress bar toward the material gate", () => {
  const good = { mother_part: 1, bolt_1: 1, bolt_2: 1, part_2hole: 1, part_3hole: 1 };
  let p;
  for (let i = 0; i < 15; i++) p = feed({ extra: { phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" }, observed: good, candidate: { status: "READY", issues: [] } });
  check("READY card", text().includes("준비 완료"), text().slice(0, 200));
  const pct = PK.progressPct(p);
  check("progress ~ 14 frames * 40ms / 1000ms", pct > 45 && pct < 65, `pct=${pct}`);
});

// 3. 조립: 확정 IN_PROGRESS 뒤 후보가 NG/IN_PROGRESS 로 흔들려도 카드는 확정만 그린다. 칩은 600ms 뒤에야.
scenario("assembly card follows confirmed, not the flickering candidate", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  check("shows 조립 중", text().includes("조립 중") && text().includes("2자리 남음"), text().slice(0, 200));
  const before = nRenders();
  for (let i = 0; i < 10; i++) feed({ candidate: i % 2 ? NG : IN_PROGRESS, confirmed: IN_PROGRESS, stable: false });   // 400ms 흔들림
  check("still 조립 중, no NG text", text().includes("조립 중") && !text().includes("볼트가 다릅니다"), text().slice(0, 200));
  check("no chip before CHIP_DELAY", !html().includes("확인 중"));
  check("no re-render during flicker", nRenders() === before, `renders=${nRenders() - before}`);
  for (let i = 0; i < 8; i++) feed({ candidate: i % 2 ? NG : IN_PROGRESS, confirmed: IN_PROGRESS, stable: false });    // 누적 720ms
  check("chip after CHIP_DELAY", html().includes("확인 중"));
  for (let i = 0; i < 3; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  check("NG once confirmed, detail from confirmed issues", text().includes("NG") && text().includes("H1 볼트가 다릅니다"), text().slice(0, 300));
  check("rings from confirmed", S.rings[1] === "ng" && S.rings[3] === "wait", JSON.stringify(S.rings));
  check("hole table row H1 is ng", html().includes('<tr class="ng"><td>H1</td>'));
});

// 4. HOLD 유예: 손이 지나가는 1초는 마지막 확정을 흐리게 유지, 1.5초를 넘기면 보류 화면, 끝나면 복귀
scenario("hold grace keeps the last verdict", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  const tBefore = renders.table, vBefore = renders.verdict;
  for (let i = 0; i < 25; i++) feed({ candidate: HOLD, confirmed: null, stable: false, extra: { status: "HOLD" } });   // 1000ms HOLD
  check("grace: still NG, chip, button-only dim", S.holdMode === "grace" && html().includes("verdict NG dim") && html().includes("확인 중"), html().slice(0, 200));
  check("grace: rings kept", S.rings[1] === "ng", JSON.stringify(S.rings));
  check("grace: geometry kept for overlay", S.geom && S.geom.pose);
  check("grace: table untouched, verdict once", renders.table === tBefore && renders.verdict - vBefore === 1, JSON.stringify(renders));
  for (let i = 0; i < 15; i++) feed({ candidate: HOLD, confirmed: null, stable: false, extra: { status: "HOLD" } });   // 누적 1600ms
  check("hold: 잠깐 + reason", S.holdMode === "hold" && text().includes("잠깐") && text().includes("Mother 안 보임"), text().slice(0, 200));
  check("hold: rings kept (not five 보류 rows), table dimmed", S.rings[1] === "ng" && table.className.includes("dim") && text().includes("마지막으로 확인된 상태"), table.className);
  check("no main re-render (video stays)", renders.main === 0, JSON.stringify(renders));
  feed({ candidate: NG, confirmed: null, stable: false, extra: { status: "HOLD" } });   // HOLD 끝, 확정은 아직 없음
  check("after hold: last verdict shown again (not dim)", text().includes("NG") && !html().includes(" dim"), html().slice(0, 200));
  for (let i = 0; i < 11; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  check("re-confirmed NG", S.holdMode === null && text().includes("H1 볼트가 다릅니다"));
});

// 0. 버전 표시가 있다 (브라우저 캐시 확인용)
check("UI version string", /0927/.test(PK.UI_VERSION), PK.UI_VERSION);

// 5. PASS 후보는 확정 전엔 큰 글씨를 바꾸지 않고, 확정되면 [작업 완료]. 영상 끝 안내.
scenario("pass appears only when confirmed; video end note", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  for (let i = 0; i < 9; i++) feed({ candidate: PASS, confirmed: IN_PROGRESS, stable: false });      // 360ms — 아직
  check("no PASS before confirmation", !text().includes("PASS") && text().includes("조립 중"), text().slice(0, 200));
  feed({ candidate: PASS, confirmed: PASS, stable: true, extra: { video_at_end: true } });
  check("PASS + button", text().includes("PASS") && html().includes('id="btn-complete"'), html().slice(0, 300));
  check("video end note", text().includes("영상이 끝나") && text().includes("영상 끝 · 마지막 장면 유지 중"));
});

// 6. 단계가 바뀌면(새 제품·조립 시작) 이전 확정을 들고 있지 않는다. 확정 전 후보 PASS/NG 는 '확인 중'.
scenario("phase and product changes drop the old verdict", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  feed({ candidate: IN_PROGRESS, confirmed: null, stable: false, extra: { status: "HOLD", phase: "ASSEMBLING" } });   // 조립 시작 직후 (confirmed 없음, 같은 단계라 shown 유지)
  check("same phase: keeps shown NG", S.shown && S.shown.status === "NG");
  product++;                                                                                                        // 새 제품
  feed({ candidate: { status: "IN_PROGRESS", issues: [] }, confirmed: null, stable: false, observed: { mother_part: 1 }, extra: { status: "HOLD", phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" } });
  check("new product: shown cleared, materials card", S.shown === null && text().includes("재료 준비"), text().slice(0, 200));
  feed({ candidate: PASS, confirmed: null, stable: false, extra: { status: "HOLD" } });   // 조립 단계 시작, 후보가 바로 PASS (있을 수 없지만 방어)
  check("unconfirmed PASS → 조립 중, not PASS", text().includes("조립 중") && !/\bPASS\b/.test(text()), text().slice(0, 200));
});

// 7. 재료→조립 전환 프레임 (phase 는 ASSEMBLING, 후보는 아직 재료 판정 READY): 자리 상태를 만들지 않고 '조립 중' 전부 남음
scenario("materials→assembly transition frame", () => {
  const good = { mother_part: 1, bolt_1: 1, bolt_2: 1, part_2hole: 1, part_3hole: 1 };
  for (let i = 0; i < 5; i++) feed({ extra: { phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" }, observed: good, candidate: { status: "READY", issues: [] } });
  feed({ candidate: { status: "READY", issues: [] }, confirmed: null, stable: true, observed: good, extra: { status: "HOLD", phase: "ASSEMBLING", evaluated_phase: "CHECK_MATERIALS" }, geometry: {} });
  check("transition: no rings, 조립 중 with every hole remaining", S.rings === null && text().includes("조립 중") && text().includes("2자리 남음") && !text().includes("확인 중"), text().slice(0, 200));
  feed({ candidate: IN_PROGRESS, confirmed: null, stable: false, extra: { status: "HOLD" } });
  check("unconfirmed candidate does not fill the rings", S.rings === null, JSON.stringify(S.rings));
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  check("confirmation fills the rings", S.rings && S.rings[1] === "wait" && S.rings[2] === "skip", JSON.stringify(S.rings));
});

// 8. 확정은 그대로인데 자리별 검출(observed) 이 프레임마다 흔들린다 — 자리 표('지금' 칸 포함) 는 다시 그려지지 않는다 (0927a 버그)
scenario("hole table ignores per-frame observed jitter", () => {
  const H1 = { "1": { bolt: [{ class_name: "bolt_1" }], part: [{ class_name: "part_2hole" }] } };
  const ONE_DONE = { status: "IN_PROGRESS", issues: MISSING(3, "part_3hole", "bolt_2") };
  for (let i = 0; i < 12; i++) feed({ candidate: ONE_DONE, confirmed: ONE_DONE, stable: true, extra: { observed: H1 } });
  check("지금 column from the stable frame", text().includes("노란 볼트 + 2구 파트") && S.rings[1] === "ok", text().slice(0, 300));
  const before = renders.table;
  const jitter = [{}, { "1": { bolt: [{ class_name: "bolt_2" }], part: [] } }, H1, { "1": { bolt: [], part: [{ class_name: "part_2hole" }] }, "2": { bolt: [{ class_name: "bolt_1" }], part: [] } }];
  for (let i = 0; i < 40; i++) feed({ candidate: i % 3 ? ONE_DONE : IN_PROGRESS, confirmed: ONE_DONE, stable: false, extra: { observed: jitter[i % 4] } });
  check("table not re-rendered while confirmed is unchanged", renders.table === before, `table renders=${renders.table - before}`);
  check("지금 column unchanged", text().includes("노란 볼트 + 2구 파트"));
});

console.log(`\n${passed} checks passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
