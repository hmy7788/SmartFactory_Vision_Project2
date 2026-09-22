-- Poka-Yoke 조립 검증 — 저장 계층 (SQLite)
-- 원칙 1) 프레임이 아니라 "변화"를 저장한다  (snapshot.events 가 비어 있지 않을 때만)
--      2) 제품 1대 = 작업 완료 버튼 1번            (PASS 이벤트 수가 아님 — 인수인계 문서)
--      3) 시간은 두 벌: ts_ms(코어의 단조 증가 ms, 계산용) + ts_utc(사람용). 길이 계산은 ts_ms 로만.
--      4) 작업자 ID 없음                             (지뢰밭 문서 — 개인별 통계 불가가 설계)
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;           -- SQLite 는 기본 OFF. 켜지 않으면 고아 이벤트가 생겨도 모른다.

-- ── 1. runs : 프로그램을 켠 세션. "그때 무슨 모델·설정이었나"를 남긴다 ──────────
CREATE TABLE IF NOT EXISTS runs (
  run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_utc       TEXT    NOT NULL,                 -- ISO8601
  ended_utc         TEXT,
  model_file        TEXT    NOT NULL,                 -- yolo_obb_parts.pt
  model_sha256      TEXT,                             -- 가중치가 바뀌었는지 판별
  config_json       TEXT    NOT NULL,                 -- mvp.json 통째로 (임계값·ROI 비율·안정화 시간)
  calibration_status TEXT   NOT NULL,                 -- UNVALIDATED_DEFAULTS / CALIBRATED_2026-09-25 ...
  camera_json       TEXT                              -- 해상도·노출·셔터 등 (Logi 설정값)
);

-- ── 2. products : 제품 1대. reset 시 생성, 작업 완료/새 작업 시 닫힘 ──────────
CREATE TABLE IF NOT EXISTS products (
  product_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id            INTEGER NOT NULL REFERENCES runs(run_id),
  recipe_id         TEXT    NOT NULL,                 -- recipe_1 / 2 / 3
  started_ms        INTEGER NOT NULL,                 -- reset 직후 첫 프레임 ts_ms
  materials_ok_ms   INTEGER,                          -- ASSEMBLY_STARTED 이벤트의 ts_ms
  closed_ms         INTEGER,                          -- 작업 완료 또는 새 작업 시각
  started_utc       TEXT    NOT NULL,
  closed_utc        TEXT,
  result            TEXT    NOT NULL DEFAULT 'OPEN'   -- OPEN | COMPLETED | ABANDONED
                    CHECK (result IN ('OPEN','COMPLETED','ABANDONED')),
  -- 아래는 닫을 때 한 번 계산해 넣는 요약 (분석 탭은 읽기가 많고 쓰기는 한 번이라 미리 계산)
  cycle_ms          INTEGER,                          -- closed - started
  materials_ms      INTEGER,                          -- materials_ok - started
  assembly_ms       INTEGER,                          -- closed - materials_ok
  ng_count          INTEGER NOT NULL DEFAULT 0,       -- status 가 NG 로 바뀐 이벤트 수 (조립 단계)
  material_ng_count INTEGER NOT NULL DEFAULT 0,       -- 재료 단계 NG 이벤트 수
  hold_count        INTEGER NOT NULL DEFAULT 0,
  first_pass        INTEGER                           -- 1 = ng_count 0 AND material_ng_count 0 AND COMPLETED
);
CREATE INDEX IF NOT EXISTS ix_products_closed ON products(closed_utc);
CREATE INDEX IF NOT EXISTS ix_products_recipe ON products(recipe_id, closed_utc);

-- ── 3. events : 상태가 바뀐 순간. snapshot.events 한 건 = 한 행 ───────────────
CREATE TABLE IF NOT EXISTS events (
  event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id        INTEGER NOT NULL REFERENCES products(product_id),
  core_seq          INTEGER NOT NULL,                 -- 코어의 event_id (reset 마다 1부터 — 그래서 product_id 가 필요)
  ts_ms             INTEGER NOT NULL,                 -- 캡처 시각, 단조 증가
  ts_utc            TEXT    NOT NULL,
  event_type        TEXT    NOT NULL,                 -- STATUS_CHANGED | ASSEMBLY_STARTED | PRODUCT_COMPLETED | PRODUCT_ABANDONED
  phase             TEXT    NOT NULL,                 -- CHECK_MATERIALS | ASSEMBLING  (전이 후)
  evaluated_phase   TEXT    NOT NULL,                 -- 이 프레임을 검사한 단계
  status            TEXT    NOT NULL,                 -- READY | IN_PROGRESS | PASS | NG | HOLD  (확정 표시)
  candidate_status  TEXT    NOT NULL,
  mother_cx         REAL,  mother_cy REAL,            -- mother_pose (HOLD 로 geometry 가 없으면 NULL)
  mother_w          REAL,  mother_h  REAL,
  mother_angle_deg  REAL,                             -- 각도 초과 HOLD 때는 루프가 major_axis() 로 따로 계산해 넣는다
  materials_json    TEXT,                             -- {"expected":{...},"observed":{...}} 재료 단계만
  observed_json     TEXT,                             -- {hole: {bolt:[{class,conf,overlap,orientation_ok}], part:[...]}}
  issues_json       TEXT    NOT NULL,                 -- 원본 그대로 (아래 event_issues 는 이걸 펼친 것)
  frame_path        TEXT,                             -- NG/HOLD 확정 프레임 JPEG 경로 — 오분류 분석용. 나머지는 NULL
  latency_ms        INTEGER                           -- 캡처 → 이 판정까지 (추론 + 기하 + 안정화 대기)
);
CREATE INDEX IF NOT EXISTS ix_events_product ON events(product_id, ts_ms);
CREATE INDEX IF NOT EXISTS ix_events_status  ON events(status, ts_utc);

-- ── 4. event_issues : issues_json 을 한 줄에 하나로 펼친 것. 파레토·히트맵은 여기서 GROUP BY ──
CREATE TABLE IF NOT EXISTS event_issues (
  event_id          INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  code              TEXT    NOT NULL,                 -- WRONG_BOLT · MISSING_PART · MATERIAL_EXCESS · MOTHER_ANGLE_OUT_OF_RANGE ...
  hole_id           INTEGER NOT NULL DEFAULT 0,       -- 0 = 자리 무관 (재료·HOLD)
  expected          TEXT    NOT NULL DEFAULT '',
  observed          TEXT    NOT NULL DEFAULT '',
  PRIMARY KEY (event_id, code, hole_id, expected, observed)
);
CREATE INDEX IF NOT EXISTS ix_issues_code ON event_issues(code, hole_id);

-- ── 5. metrics : 1분 버킷. 프레임마다 쓰지 않는다 ────────────────────────────
CREATE TABLE IF NOT EXISTS metrics (
  run_id            INTEGER NOT NULL REFERENCES runs(run_id),
  bucket_utc        TEXT    NOT NULL,                 -- 분 단위로 자른 시각
  frames            INTEGER NOT NULL,
  fps               REAL    NOT NULL,
  infer_ms_p50      REAL, infer_ms_p95 REAL,
  total_ms_p50      REAL, total_ms_p95 REAL,          -- 추론 + 기하 + 판정
  frame_gap_max_ms  INTEGER,
  frame_gap_over    INTEGER NOT NULL DEFAULT 0,       -- max_frame_gap 초과 횟수
  hold_frames       INTEGER NOT NULL DEFAULT 0,       -- candidate 가 HOLD 였던 프레임 수 → 보류 비율
  PRIMARY KEY (run_id, bucket_utc)
);

-- ══════════════════════════════════════════════════════════════════════════
-- 분석 탭이 실제로 던지는 쿼리 (스키마가 이걸 감당하는지로 설계를 검증)
-- ══════════════════════════════════════════════════════════════════════════

-- 첫 시도 통과율 (FPY) · 7일 · 레시피별
-- SELECT recipe_id, ROUND(100.0*AVG(first_pass),1) AS fpy, COUNT(*) AS n
--   FROM products WHERE result='COMPLETED' AND closed_utc >= datetime('now','-7 days')
--  GROUP BY recipe_id;

-- NG 유형 파레토 (조립 단계, 확정 NG 이벤트만)
-- SELECT i.code, COUNT(*) AS n
--   FROM event_issues i JOIN events e USING(event_id)
--  WHERE e.status='NG' AND e.evaluated_phase='ASSEMBLING'
--  GROUP BY i.code ORDER BY n DESC;

-- 자리 × 레시피 히트맵
-- SELECT p.recipe_id, i.hole_id, COUNT(*) AS n
--   FROM event_issues i JOIN events e USING(event_id) JOIN products p USING(product_id)
--  WHERE e.status='NG' AND i.hole_id BETWEEN 1 AND 5
--  GROUP BY p.recipe_id, i.hole_id;

-- NG → 복구 시간 (다음 상태 변화까지). LEAD 는 SQLite 3.25+
-- SELECT product_id, ts_ms,
--        LEAD(ts_ms) OVER (PARTITION BY product_id ORDER BY ts_ms) - ts_ms AS recover_ms
--   FROM events WHERE status IN ('NG','IN_PROGRESS','PASS')
--  -- 여기서 status='NG' 인 행만 남기면 회복 시간 분포

-- 보류 원인
-- SELECT i.code, COUNT(*) FROM event_issues i JOIN events e USING(event_id)
--  WHERE e.status='HOLD' GROUP BY i.code ORDER BY 2 DESC;

-- 클래스별 confidence 분포 (판정에 쓰인 검출만) — observed_json 을 펼친다
-- SELECT json_extract(d.value,'$.class_name') AS cls, json_extract(d.value,'$.confidence') AS conf
--   FROM events e, json_each(e.observed_json) h, json_each(h.value,'$.bolt') d
--  WHERE e.status IN ('PASS','NG')
-- UNION ALL  ... '$.part' 도 같은 식
