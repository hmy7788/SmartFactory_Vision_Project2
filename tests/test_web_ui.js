/* 작업 화면(web/static/app.js) 의 파생 상태 검사 — 브라우저 없이 node 로 payload 순서를 넣어 본다.
   실행:  node tests/test_web_ui.js      (tests/test_web.py 의 UiLogicTests 가 같은 것을 부른다)
   검사하는 것: 프레임마다 흔들리는 후보·수량이 화면을 흔들지 않는지 (확정만 그림 · 재료 수량 최빈값),
   보류(HOLD) 가 작업 화면에 나타나지 않는지 (0927c — 작업자는 OK/NG 만 본다). */
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
const NULL_IDS = new Set(["#overlay", "#prog", "#btn-complete", "#verdict .hint .act"]);
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
const HOLD = { status: "HOLD", issues: [{ code: "AMBIGUOUS_ASSOCIATION", hole_id: 0, expected: "", observed: "part_2hole" }] };      // 손 가림
const TILT = { status: "HOLD", issues: [{ code: "MOTHER_ANGLE_OUT_OF_RANGE", hole_id: 0, expected: "", observed: "" }] };
const HOLD_WORDS = /보류|잠깐|확인 중/;   // 작업 화면에 나오면 안 되는 말
const PASS = { status: "PASS", issues: [] };

// 1. 재료 수량이 프레임마다 흔들려도 표·카드는 최빈값으로 조용하다
scenario("materials counts are smoothed", () => {
  const good = { mother_part: 1, bolt_1: 1, bolt_2: 1, part_2hole: 1, part_3hole: 0 }, flick = { mother_part: 1, bolt_1: 0, bolt_2: 1, part_2hole: 2, part_3hole: 0 };
  for (let i = 0; i < 30; i++) feed({ phase: "CHECK_MATERIALS", extra: { phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" }, observed: i % 3 === 2 ? flick : good,
                                     candidate: { status: "IN_PROGRESS", issues: [] } });
  check("matView is the majority", S.matView.bolt_1 === 1 && S.matView.part_2hole === 1, JSON.stringify(S.matView));
  check("card names the missing part from the smoothed counts", text().includes("3구 파트 1개 더 놓으세요"), text().slice(0, 300));
  check("few re-renders despite flicker", renders.table + renders.verdict <= 4 && renders.main <= 1, JSON.stringify(renders));
  check("no hold/checking words in materials phase", !HOLD_WORDS.test(text()));
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

// 3. 조립: 확정 IN_PROGRESS 뒤 후보가 NG/IN_PROGRESS 로 흔들려도 카드는 확정만 그린다. '확인 중' 같은 말도 없다.
scenario("assembly card follows confirmed, not the flickering candidate", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  check("shows 조립 중", text().includes("조립 중") && text().includes("2자리 남음"), text().slice(0, 200));
  const before = nRenders();
  for (let i = 0; i < 10; i++) feed({ candidate: i % 2 ? NG : IN_PROGRESS, confirmed: IN_PROGRESS, stable: false });   // 400ms 흔들림
  check("still 조립 중, no NG text", text().includes("조립 중") && !text().includes("볼트가 다릅니다"), text().slice(0, 200));
  for (let i = 0; i < 20; i++) feed({ candidate: i % 2 ? NG : IN_PROGRESS, confirmed: IN_PROGRESS, stable: false });   // 누적 1.2초
  check("no checking words even after a long flicker", !HOLD_WORDS.test(text()));
  check("no re-render during flicker", nRenders() === before, `renders=${nRenders() - before}`);
  for (let i = 0; i < 3; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  check("NG once confirmed, detail from confirmed issues", text().includes("NG") && text().includes("H1 볼트가 다릅니다"), text().slice(0, 300));
  check("rings from confirmed", S.rings[1] === "ng" && S.rings[3] === "wait", JSON.stringify(S.rings));
  check("hole table row H1 is ng", html().includes('<tr class="ng"><td>H1</td>') && text().includes("✕ 틀림"));
  check("primary issue also shows the actionable detail sentence, not just the title",
        text().includes("빼고 노란 볼트로 바꿔주세요"), text().slice(0, 300));
});

// 3b. PART_WRONG_SIDE는 사람이 읽는 문장으로 나와야 한다 (raw 코드 그대로 뜨던 버그)
scenario("PART_WRONG_SIDE gets a full Korean action sentence, not the raw code", () => {
  const WRONG_SIDE = { status: "NG", issues: [{ code: "PART_WRONG_SIDE", hole_id: 1, expected: "part_2hole", observed: "part_2hole" }] };
  for (let i = 0; i < 12; i++) feed({ candidate: WRONG_SIDE, confirmed: WRONG_SIDE, stable: true });
  check("shows the action sentence, never the raw code",
        text().includes("Mother 아래쪽에 달려 있습니다") && text().includes("위쪽으로 옮겨주세요") && !text().includes("PART_WRONG_SIDE"),
        text().slice(0, 300));
  check("body doesn't say to empty the slot (part itself is correct, just mispositioned)",
        !text().includes("이 자리는 비워 둡니다"));
});

// 4. 보류(HOLD) 는 작업 화면에 없다: 손 가림이 몇 초 이어져도 마지막 NG 가 그대로, 표·카드 다시 그리기 0, 보류 말 없음
scenario("hold never reaches the worker screen", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  const before = nRenders();
  for (let i = 0; i < 25; i++) feed({ candidate: HOLD, confirmed: null, stable: false, extra: { status: "HOLD" } });   // 1초
  check("short hold: nothing changes", nRenders() === before && S.geom && S.geom.pose, `renders=${nRenders() - before}`);
  for (let i = 0; i < 100; i++) feed({ candidate: HOLD, confirmed: null, stable: false, extra: { status: "HOLD" } });  // 누적 5초 (손 가림)
  check("long hand hold: still NG with detail, no hold words, no hint", text().includes("H1 볼트가 다릅니다") && !HOLD_WORDS.test(text()) && !S.holdHint, text().slice(0, 300));
  check("long hand hold: rings kept, no re-render", S.rings[1] === "ng" && nRenders() === before, `renders=${nRenders() - before}`);
  check("overlay geometry dropped after GEOM_KEEP_MS", !S.geom);
  check("no main re-render (video stays)", renders.main === 0, JSON.stringify(renders));
  for (let i = 0; i < 11; i++) feed({ candidate: NG, confirmed: NG, stable: true });
  check("re-confirmed NG", text().includes("H1 볼트가 다릅니다"));
});

// 4b. 작업자가 고칠 보류(Mother 기울어짐) 가 3초 넘으면 맨 아래 한 줄만 — 큰 글씨·색은 그대로
scenario("actionable hold adds one hint line after HOLD_HINT_MS", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  for (let i = 0; i < 70; i++) feed({ candidate: TILT, confirmed: null, stable: false, extra: { status: "HOLD", mother_angle_deg: 26 } });   // 2.8초
  check("tilt < 3s: no hint", !S.holdHint && !text().includes("똑바로"));
  for (let i = 0; i < 10; i++) feed({ candidate: TILT, confirmed: null, stable: false, extra: { status: "HOLD", mother_angle_deg: 26 } });   // 3.2초
  check("tilt > 3s: one hint line, card still 조립 중", S.holdHint === "MOTHER_ANGLE_OUT_OF_RANGE" && text().includes("Mother 를 똑바로 놓아 주세요 (지금 26° 기울어짐)") && text().includes("조립 중") && !/보류|잠깐/.test(text()), text().slice(0, 300));
  feed({ candidate: IN_PROGRESS, confirmed: null, stable: false, extra: { status: "HOLD" } });
  check("hint gone once the hold ends", !S.holdHint && !text().includes("똑바로"));
});

// 4c. PASS 중 보류: PASS 그대로, [작업 완료] 만 잠김 (서버가 409 를 줄 버튼을 누르게 두지 않는다)
scenario("pass during hold keeps PASS but locks the button", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: PASS, confirmed: PASS, stable: true });
  check("PASS + enabled button", text().includes("PASS") && html().includes('id="btn-complete" >'), html().slice(-400));
  for (let i = 0; i < 10; i++) feed({ candidate: HOLD, confirmed: null, stable: false, extra: { status: "HOLD" } });
  check("PASS kept, button disabled, no hold words", text().includes("PASS") && html().includes('id="btn-complete" disabled') && !HOLD_WORDS.test(text()), html().slice(-400));
  feed({ candidate: PASS, confirmed: PASS, stable: true });
  check("button enabled again", html().includes('id="btn-complete" >'));
});

// 0. 버전 표시가 있다 (브라우저 캐시 확인용)
check("UI version string", /09\d\d/.test(PK.UI_VERSION), PK.UI_VERSION);

// 5. PASS 후보는 확정 전엔 큰 글씨를 바꾸지 않고, 확정되면 [작업 완료]. 영상 끝 안내.
scenario("pass appears only when confirmed; video end note", () => {
  for (let i = 0; i < 12; i++) feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true });
  for (let i = 0; i < 9; i++) feed({ candidate: PASS, confirmed: IN_PROGRESS, stable: false });      // 360ms — 아직
  check("no PASS before confirmation", !text().includes("PASS") && text().includes("조립 중"), text().slice(0, 200));
  feed({ candidate: PASS, confirmed: PASS, stable: true, extra: { video_at_end: true } });
  check("PASS + button", text().includes("PASS") && html().includes('id="btn-complete"'), html().slice(0, 300));
  check("video end note", text().includes("영상이 끝나") && text().includes("영상 끝 · 마지막 장면 유지 중"));
});

// 6. 단계가 바뀌면(새 제품·조립 시작) 이전 확정을 들고 있지 않는다. 확정 전 후보 PASS/NG 는 '조립 중'.
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
  check("transition: no rings, 조립 중 with every hole remaining", S.rings === null && text().includes("조립 중") && text().includes("2자리 남음") && !HOLD_WORDS.test(text()), text().slice(0, 200));
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

// 9. 조립체를 180도 돌려 core가 반대쪽 끝에서 읽으면(geometry.hole_numbering === "mirrored"),
// p.observed 는 물리적 구멍 번호(카메라가 본 실제 위치) 기준이라 레시피 번호와 반대다 — H1(레시피)의
// 내용은 물리적으로 구멍 5 자리에 있다. obsNames() 가 이 관계(6-h)를 되짚어야 "지금" 칸이 맞게 뜬다.
scenario("hole table relabels observed by mother_hole when mirrored (180-degree rotation)", () => {
  const physical5 = { "5": { bolt: [{ class_name: "bolt_1" }], part: [{ class_name: "part_2hole" }] } };
  const oneDone = { status: "IN_PROGRESS", issues: MISSING(3, "part_3hole", "bolt_2") };
  const mirroredGeom = { pose: { center: [640, 360], u: [1, 0], v: [0, 1], width: 800, height: 80, angle_rad: 0 },
                         holes: { 5: [980, 360], 3: [640, 360] }, hole_numbering: "mirrored" };
  for (let i = 0; i < 12; i++)
    feed({ candidate: oneDone, confirmed: oneDone, stable: true, extra: { observed: physical5, geometry: mirroredGeom } });
  check("recipe H1's ring is ok (issues are already recipe-numbered)", S.rings[1] === "ok", JSON.stringify(S.rings));
  check("지금 column shows H1's content read from physical hole 5", text().includes("노란 볼트 + 2구 파트"), text().slice(0, 300));
});

// 10. MES 연동: 작업지시가 없으면 '대기', 있으면 헤더에 작업지시 줄(드롭다운 없음), 수량을 채우면 '작업지시 완료'
scenario("MES work order drives the header and waiting card", () => {
  const mes = (wo, connected = true) => ({ mes: { enabled: true, connected, station_id: "VIS-01", broker: "localhost:1883", pending: 0, work_order: wo } });
  const WO = { work_order_id: "WO-7", recipe_id: "recipe_1", recipe_version: 3, quantity: 10, done: 3, status: "IN_PROGRESS" };
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true, extra: mes(null) });
  check("no work order → 대기", text().includes("대기") && text().includes("작업지시를 기다리는 중") && !html().includes("btn-complete"), text().slice(0, 200));
  check("header: no recipe dropdown", !hmid._html.includes("recipe-select") && hmid._html.includes("작업지시"), hmid._html);
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true, extra: mes(WO) });
  check("active → normal card + WO line", text().includes("조립 중") && hmid._html.includes("WO-7") && hmid._html.includes("3/10") && hmid._html.includes("v3"), hmid._html);
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true, extra: mes(WO, false) });
  check("broker down → red dot only, card unchanged", hmid._html.includes('class="wo off"') && text().includes("조립 중"));
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true, extra: mes({ ...WO, done: 10, status: "COMPLETED" }) });
  check("completed → 작업지시 완료 10/10", text().includes("작업지시 완료") && text().includes("10/10"), text().slice(0, 200));
  const NEXT = [{ work_order_id: "WO-8", recipe_id: "recipe_2", quantity: 3 }, { work_order_id: "WO-9", recipe_id: "recipe_3", quantity: 1 }];
  feed({ candidate: IN_PROGRESS, confirmed: IN_PROGRESS, stable: true, extra: mes({ ...WO, next: NEXT }) });
  check("MES queue → header shows the next line", hmid._html.includes("다음 recipe_2 × 3") && hmid._html.includes("외 1건"), hmid._html);
});

// 11. [작업 완료] 직후 완성품 반출 대기 (0928b): 완성품이 작업대에 남아 있는 동안은 재료 확인·[작업 완료] 대신 '완성품 반출' 카드.
//     MES 대기 카드보다 앞선다. 비었다고 세는 동안은 막대만 제자리에서 차오르고, 끝나면(새 제품) 평소 재료 확인으로 돌아온다.
scenario("after 작업 완료 the removal card holds until the table is clear", () => {
  const MAT = { phase: "CHECK_MATERIALS", evaluated_phase: "CHECK_MATERIALS" };
  const wait = (a, more = {}) => feed({ candidate: { status: "IN_PROGRESS", issues: [] }, observed: {}, extra: { ...MAT, product_id: null, await_clear: a, ...more } });
  wait({ mother: true, attached: ["bolt_1", "bolt_2", "part_2hole", "part_3hole"], clear_pct: 0, clear_ms: 1000 });
  check("removal card instead of the materials check", text().includes("완성품 반출") && text().includes("작업대에서 완성품을 치워 주세요") && !text().includes("재료 준비"), text().slice(0, 300));
  check("no complete button while waiting", !html().includes("btn-complete"));
  check("materials table is not counted", table._html.includes("대기") && !table._html.includes("개 더") && table._html.includes("완성품을 치우면"), table._html.slice(0, 200));
  check("lists what is still on the Mother", text().includes("아직 Mother 에 꽂혀 있는 것") && text().includes("노란 볼트") && text().includes("3구 파트"));
  check("no hold/checking words", !HOLD_WORDS.test(text()), text().slice(0, 300));
  const MES_IDLE = { mes: { enabled: true, connected: true, station_id: "VIS-01", broker: "localhost:1883", pending: 0,
                            work_order: { work_order_id: "WO-7", recipe_id: "recipe_1", recipe_version: 3, quantity: 3, done: 3, status: "COMPLETED" } } };
  wait({ mother: true, attached: ["part_2hole"], clear_pct: 0, clear_ms: 1000 }, MES_IDLE);
  check("removal comes before the MES waiting card", text().includes("완성품 반출") && !text().includes("작업지시 완료"), text().slice(0, 300));
  wait({ mother: false, attached: [], clear_pct: 30, clear_ms: 1000 });
  check("clear → countdown bar", html().includes('id="prog-clear"') && text().includes("다음 제품 재료 확인까지"), text().slice(0, 300));
  const before = renders.verdict + renders.table;
  for (const pct of [45, 60, 80, 95]) wait({ mother: false, attached: [], clear_pct: pct, clear_ms: 1000 });
  check("countdown does not re-render the card", renders.verdict + renders.table === before, JSON.stringify(renders));
  product++;
  feed({ candidate: PASS, confirmed: PASS, stable: true, extra: { clear_wait: true } });
  check("live camera PASS hint mentions clearing the table", text().includes("완성품을 작업대에서 치우면") && html().includes("btn-complete"), text().slice(0, 400));
  product++;
  feed({ candidate: { status: "IN_PROGRESS", issues: [] }, observed: {}, extra: { ...MAT, await_clear: null } });
  check("new product → normal materials check", text().includes("재료 준비") && !text().includes("완성품 반출") && !table._html.includes("대기"), text().slice(0, 300));
});

console.log(`\n${passed} checks passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
