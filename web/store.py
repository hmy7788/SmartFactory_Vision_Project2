"""SQLite 저장 계층 — 코어(src/) 밖에서 Snapshot 을 받아 '변화'만 기록한다.

역할 (state_machine_development_guidelines.md 의 ``database/  # 다른 담당: 이벤트 저장``):

    쓰기  open_run → open_product → record(snapshot)… → close_product → close_run
    읽기  history · timeline · fpy · cycle · pareto · heatmap · recovery · hold_reasons · confidence · metrics

원칙
    1. 프레임이 아니라 변화를 저장한다. record() 는 snapshot.events 가 비어 있으면 아무것도 쓰지 않는다.
       → 제품 1대에 이벤트 몇 건뿐이라 동기 INSERT 로 충분하다. 프레임마다 쓰게 되면 그때 큐로 옮긴다.
    2. 제품 1대 = close_product() 1번. PASS 이벤트 수가 아니다 (docs/state_machine_handoff.md).
    3. 시간은 두 벌. ts_ms(코어의 단조 증가 ms) 로만 길이를 계산하고, ts_utc 는 사람이 읽는 용도.
    4. 작업자 ID 컬럼은 없다. 개인별 통계가 '정책상' 이 아니라 '구조상' 불가능해야 한다.

사용 (web/pipeline.py 에서)::

    store = Store("data/pokayoke.db")
    run = store.open_run("model/yolo_obb_parts.pt", config)
    product = store.open_product(run, recipe.recipe_id, started_ms=first_ts)
    ...
    snapshot = service.update(frame)
    store.record(product, snapshot, latency_ms=now_ms - frame.timestamp_ms)
    store.frame(run, infer_ms, total_ms, gap_ms, hold=snapshot.candidate.status is Status.HOLD)
    ...
    store.close_product(product, closed_ms=now_ms)          # [작업 완료]
    store.close_product(product, closed_ms=now_ms, result="ABANDONED")   # [새 작업]
    store.close_run(run)

표준 라이브러리만 쓴다. 코어와 마찬가지로 GPU·모델 없이 테스트할 수 있다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from math import degrees
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
STATUS_CHANGED, ASSEMBLY_STARTED = "STATUS_CHANGED", "ASSEMBLY_STARTED"
PRODUCT_COMPLETED, PRODUCT_ABANDONED = "PRODUCT_COMPLETED", "PRODUCT_ABANDONED"


def utc_now() -> str:
    """SQLite 의 datetime('now') 와 같은 형식. 문자열 비교가 그대로 시간 비교가 된다."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _val(x: Any) -> Any:
    """Enum → value. 코어의 Status/Phase 는 str Enum 이라 그대로 넣어도 되지만 명시한다."""
    return getattr(x, "value", x)


def _json(obj: Any) -> str:
    def default(o):
        if is_dataclass(o):
            return asdict(o)
        if hasattr(o, "value"):
            return o.value
        raise TypeError(f"not serializable: {type(o).__name__}")
    return json.dumps(obj, ensure_ascii=False, default=default)


def percentile(values: list[float], p: float) -> float | None:
    """nearest-rank. 통계 라이브러리 없이 p50/p90/p95 정도는 이걸로 충분하다."""
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[k]


class Store:
    def __init__(self, path: str | Path, max_frame_gap_ms: int = 250):
        self.path = Path(path)
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # 파이프라인 스레드와 웹 스레드가 같은 연결을 쓴다. Lock 하나로 직렬화한다.
        self._con = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._con.execute("PRAGMA foreign_keys = ON")     # executescript 뒤에 한 번 더 — 연결 단위 설정이라서
        self.max_frame_gap_ms = max_frame_gap_ms
        self._bucket: dict | None = None

    # ── 내부 ────────────────────────────────────────────────
    def _x(self, sql: str, params: Iterable | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._con.execute(sql, params if isinstance(params, dict) else tuple(params))

    def _rows(self, sql: str, params: Iterable = ()) -> list[dict]:
        return [dict(r) for r in self._x(sql, params).fetchall()]

    def _one(self, sql: str, params: Iterable = ()):
        row = self._x(sql, params).fetchone()
        return dict(row) if row is not None else None

    # ── runs ────────────────────────────────────────────────
    def open_run(self, model_file: str, config: dict, calibration_status: str | None = None,
                 camera: dict | None = None, model_sha256: str | None = None) -> int:
        cur = self._x(
            "INSERT INTO runs(started_utc, model_file, model_sha256, config_json, calibration_status, camera_json) "
            "VALUES (?,?,?,?,?,?)",
            (utc_now(), model_file, model_sha256, _json(config),
             calibration_status or config.get("calibration_status", "UNKNOWN"),
             _json(camera) if camera else None))
        return cur.lastrowid

    def close_run(self, run_id: int) -> None:
        self.flush_metrics()
        self._x("UPDATE runs SET ended_utc=? WHERE run_id=?", (utc_now(), run_id))

    # ── products ────────────────────────────────────────────
    def open_product(self, run_id: int, recipe_id: str, started_ms: int, ts_utc: str | None = None) -> int:
        """service.reset() 직후 첫 프레임에서 부른다. 열린 제품이 남아 있으면 먼저 ABANDONED 로 닫는다."""
        for stale in self._rows("SELECT product_id FROM products WHERE run_id=? AND result='OPEN'", (run_id,)):
            self.close_product(stale["product_id"], started_ms, result="ABANDONED", ts_utc=ts_utc)
        cur = self._x("INSERT INTO products(run_id, recipe_id, started_ms, started_utc) VALUES (?,?,?,?)",
                      (run_id, recipe_id, int(started_ms), ts_utc or utc_now()))
        return cur.lastrowid

    def close_product(self, product_id: int, closed_ms: int, result: str = "COMPLETED",
                      ts_utc: str | None = None) -> dict:
        """[작업 완료] → COMPLETED, [새 작업] → ABANDONED. 요약 컬럼을 여기서 한 번 계산한다."""
        if result not in ("COMPLETED", "ABANDONED"):
            raise ValueError("result must be COMPLETED or ABANDONED")
        product = self._one("SELECT * FROM products WHERE product_id=?", (product_id,))
        if product is None:
            raise KeyError(f"product {product_id} not found")
        if product["result"] != "OPEN":
            raise ValueError(f"product {product_id} already {product['result']}")
        events = self._rows("SELECT event_type, evaluated_phase, phase, status, ts_ms FROM events "
                            "WHERE product_id=? ORDER BY ts_ms, event_id", (product_id,))
        closed_ms = int(closed_ms)
        started_ms = product["started_ms"]
        materials_ok = next((e["ts_ms"] for e in events if e["event_type"] == ASSEMBLY_STARTED), None)

        # NG/HOLD 는 '에피소드' 로 센다. NG → HOLD → NG 는 한 번이지 두 번이 아니다.
        ng = material_ng = hold = 0
        prev_non_hold, prev = None, None
        for e in events:
            if e["event_type"] == ASSEMBLY_STARTED:       # 전환 프레임의 HOLD 는 설계상 HOLD — 세지 않는다
                prev_non_hold, prev = None, None
                continue
            s = e["status"]
            if s == "HOLD" and prev != "HOLD":
                hold += 1
            if s == "NG" and prev_non_hold != "NG":
                if e["evaluated_phase"] == "ASSEMBLING":
                    ng += 1
                else:
                    material_ng += 1
            if s != "HOLD":
                prev_non_hold = s
            prev = s

        last = events[-1] if events else {"phase": "CHECK_MATERIALS", "status": "HOLD"}
        self._x("INSERT INTO events(product_id, core_seq, ts_ms, ts_utc, event_type, phase, evaluated_phase, "
                "status, candidate_status, issues_json) VALUES (?,?,?,?,?,?,?,?,?,'[]')",
                (product_id, 0, closed_ms, ts_utc or utc_now(),
                 PRODUCT_COMPLETED if result == "COMPLETED" else PRODUCT_ABANDONED,
                 last["phase"], last["phase"], last["status"], last["status"]))
        summary = {
            "closed_ms": closed_ms, "closed_utc": ts_utc or utc_now(), "result": result,
            "materials_ok_ms": materials_ok,
            "cycle_ms": closed_ms - started_ms,
            "materials_ms": (materials_ok - started_ms) if materials_ok is not None else None,
            "assembly_ms": (closed_ms - materials_ok) if materials_ok is not None else None,
            "ng_count": ng, "material_ng_count": material_ng, "hold_count": hold,
            "first_pass": int(result == "COMPLETED" and ng == 0 and material_ng == 0),
        }
        self._x("UPDATE products SET closed_ms=:closed_ms, closed_utc=:closed_utc, result=:result, "
                "materials_ok_ms=:materials_ok_ms, cycle_ms=:cycle_ms, materials_ms=:materials_ms, "
                "assembly_ms=:assembly_ms, ng_count=:ng_count, material_ng_count=:material_ng_count, "
                "hold_count=:hold_count, first_pass=:first_pass WHERE product_id=:pid",
                {**summary, "pid": product_id})
        return {"product_id": product_id, **summary}

    # ── events ──────────────────────────────────────────────
    def record(self, product_id: int, snapshot, *, mother_angle_deg: float | None = None,
               latency_ms: int | None = None, frame_path: str | None = None,
               ts_utc: str | None = None) -> int:
        """Snapshot 하나를 받아 events 가 있으면 쓴다. 돌아오는 값은 쓴 이벤트 수(대개 0).

        mother_angle_deg: 각도 초과 HOLD 는 geometry 가 비어 각도를 모른다. 파이프라인이 Mother 검출로
        mother_frame.major_axis() 를 한 번 더 불러 넘겨 주면 그 값을 쓴다. 없으면 pose 에서 계산한다.
        """
        events = getattr(snapshot, "events", ()) or ()
        if not events:
            return 0
        n = 0
        with self._lock:
            self._con.execute("BEGIN")
            for ev in events:
                pose = ev.get("mother_pose") or {}
                angle = mother_angle_deg
                if angle is None and pose:
                    angle = degrees(pose["angle_rad"])
                candidate = ev["candidate"]
                cur = self._con.execute(
                    "INSERT INTO events(product_id, core_seq, ts_ms, ts_utc, event_type, phase, evaluated_phase, "
                    "status, candidate_status, mother_cx, mother_cy, mother_w, mother_h, mother_angle_deg, "
                    "materials_json, observed_json, issues_json, frame_path, latency_ms) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (product_id, ev["event_id"], int(ev["timestamp_ms"]), ts_utc or utc_now(),
                     ev["event_type"], _val(ev["phase"]), _val(ev["from_phase"]),
                     _val(ev["status"]), _val(candidate["status"]),
                     (pose.get("center") or (None, None))[0], (pose.get("center") or (None, None))[1],
                     pose.get("width"), pose.get("height"), angle,
                     _json(ev.get("materials") or {}) if ev.get("materials") else None,
                     _json(ev.get("observed") or {}) if ev.get("observed") else None,
                     _json(candidate.get("issues", [])), frame_path, latency_ms))
                for issue in candidate.get("issues", []):
                    self._con.execute(
                        "INSERT OR IGNORE INTO event_issues(event_id, code, hole_id, expected, observed) "
                        "VALUES (?,?,?,?,?)",
                        (cur.lastrowid, issue["code"], int(issue.get("hole_id", 0)),
                         issue.get("expected", ""), issue.get("observed", "")))
                n += 1
            self._con.execute("COMMIT")
        return n

    # ── metrics (1분 버킷) ──────────────────────────────────
    def frame(self, run_id: int, infer_ms: float, total_ms: float, gap_ms: float | None = None,
              hold: bool = False, ts_utc: str | None = None) -> None:
        """프레임마다 부르지만 메모리에만 쌓고, 분이 바뀔 때 한 행을 쓴다."""
        bucket = (ts_utc or utc_now())[:16] + ":00"
        b = self._bucket
        if b is None or b["run_id"] != run_id or b["bucket"] != bucket:
            self.flush_metrics()
            b = self._bucket = {"run_id": run_id, "bucket": bucket, "infer": [], "total": [],
                                "gap_max": 0, "gap_over": 0, "hold": 0}
        b["infer"].append(float(infer_ms))
        b["total"].append(float(total_ms))
        if gap_ms is not None:
            b["gap_max"] = max(b["gap_max"], int(gap_ms))
            if gap_ms > self.max_frame_gap_ms:
                b["gap_over"] += 1
        if hold:
            b["hold"] += 1

    def flush_metrics(self) -> None:
        b, self._bucket = self._bucket, None
        if not b or not b["infer"]:
            return
        frames = len(b["infer"])
        self._x("INSERT OR REPLACE INTO metrics(run_id, bucket_utc, frames, fps, infer_ms_p50, infer_ms_p95, "
                "total_ms_p50, total_ms_p95, frame_gap_max_ms, frame_gap_over, hold_frames) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (b["run_id"], b["bucket"], frames, frames / 60.0,
                 percentile(b["infer"], 50), percentile(b["infer"], 95),
                 percentile(b["total"], 50), percentile(b["total"], 95),
                 b["gap_max"], b["gap_over"], b["hold"]))

    # ── 읽기 : 이력 탭 ──────────────────────────────────────
    def history(self, limit: int = 50, recipe_id: str | None = None, result: str | None = None,
                ng_only: bool = False, hold_only: bool = False) -> list[dict]:
        where, params = ["result != 'OPEN'"], []
        if recipe_id:
            where.append("recipe_id=?"); params.append(recipe_id)
        if result:
            where.append("result=?"); params.append(result)
        if ng_only:
            where.append("(ng_count > 0 OR material_ng_count > 0)")
        if hold_only:
            where.append("hold_count > 0")
        params.append(limit)
        return self._rows(f"SELECT * FROM products WHERE {' AND '.join(where)} "
                          "ORDER BY closed_ms DESC, product_id DESC LIMIT ?", params)

    def timeline(self, product_id: int) -> list[dict]:
        rows = self._rows("SELECT event_id, core_seq, ts_ms, ts_utc, event_type, phase, evaluated_phase, status, "
                          "candidate_status, mother_angle_deg, issues_json, latency_ms, frame_path FROM events "
                          "WHERE product_id=? ORDER BY ts_ms, event_id", (product_id,))
        for r in rows:
            r["issues"] = json.loads(r.pop("issues_json") or "[]")
        return rows

    # ── 읽기 : 분석 탭 ──────────────────────────────────────
    def fpy(self, days: int = 7) -> dict:
        rows = self._rows("SELECT recipe_id, ROUND(100.0*AVG(first_pass),1) AS fpy, COUNT(*) AS n FROM products "
                          "WHERE result='COMPLETED' AND closed_utc >= datetime('now', ?) GROUP BY recipe_id",
                          (f"-{int(days)} days",))
        total = self._one("SELECT ROUND(100.0*AVG(first_pass),1) AS fpy, COUNT(*) AS n FROM products "
                          "WHERE result='COMPLETED' AND closed_utc >= datetime('now', ?)", (f"-{int(days)} days",))
        return {"by_recipe": rows, "total": total}

    def fpy_daily(self, days: int = 7) -> list[dict]:
        """분석 탭 추이선. 날짜별 첫 시도 통과율 — 하루에 완료가 없으면 행이 없다 (0 으로 채우지 않는다)."""
        return self._rows("SELECT substr(closed_utc,1,10) AS day, ROUND(100.0*AVG(first_pass),1) AS fpy, COUNT(*) AS n "
                          "FROM products WHERE result='COMPLETED' AND closed_utc >= datetime('now', ?) "
                          "GROUP BY day ORDER BY day", (f"-{int(days)} days",))

    def cycle(self, days: int = 7) -> dict[str, dict]:
        out = {}
        for r in self._rows("SELECT recipe_id, cycle_ms, materials_ms, assembly_ms FROM products "
                            "WHERE result='COMPLETED' AND closed_utc >= datetime('now', ?)", (f"-{int(days)} days",)):
            d = out.setdefault(r["recipe_id"], {"cycle": [], "materials": [], "assembly": []})
            for k in ("cycle", "materials", "assembly"):
                if r[f"{k}_ms"] is not None:
                    d[k].append(r[f"{k}_ms"])
        return {rid: {k: {"median": percentile(v, 50), "p90": percentile(v, 90), "n": len(v)} for k, v in d.items()}
                for rid, d in out.items()}

    def pareto(self, days: int = 7, phase: str = "ASSEMBLING") -> list[dict]:
        rows = self._rows("SELECT i.code, COUNT(*) AS n FROM event_issues i JOIN events e USING(event_id) "
                          "WHERE e.status='NG' AND e.evaluated_phase=? AND e.ts_utc >= datetime('now', ?) "
                          "GROUP BY i.code ORDER BY n DESC", (phase, f"-{int(days)} days"))
        total, acc = sum(r["n"] for r in rows) or 1, 0
        for r in rows:
            acc += r["n"]
            r["cum_pct"] = round(100.0 * acc / total, 1)
        return rows

    def heatmap(self, days: int = 7) -> dict[str, dict[int, int]]:
        out: dict[str, dict[int, int]] = {}
        for r in self._rows("SELECT p.recipe_id, i.hole_id, COUNT(*) AS n FROM event_issues i "
                            "JOIN events e USING(event_id) JOIN products p USING(product_id) "
                            "WHERE e.status='NG' AND i.hole_id BETWEEN 1 AND 5 AND e.ts_utc >= datetime('now', ?) "
                            "GROUP BY p.recipe_id, i.hole_id", (f"-{int(days)} days",)):
            out.setdefault(r["recipe_id"], {h: 0 for h in range(1, 6)})[r["hole_id"]] = r["n"]
        return out

    def recovery(self, days: int = 7) -> dict:
        """조립 NG 확정 → 다음 IN_PROGRESS/PASS 확정까지 ms. 피드백이 실제로 고쳐지게 하는지의 지표."""
        rows = self._rows(
            "SELECT status, nxt - ts_ms AS ms FROM ("
            "  SELECT status, ts_ms, LEAD(ts_ms) OVER (PARTITION BY product_id ORDER BY ts_ms, event_id) AS nxt "
            "  FROM events WHERE status IN ('NG','IN_PROGRESS','PASS') AND evaluated_phase='ASSEMBLING' "
            "  AND event_type=? AND ts_utc >= datetime('now', ?)"
            ") WHERE status='NG' AND nxt IS NOT NULL", (STATUS_CHANGED, f"-{int(days)} days"))
        values = [r["ms"] for r in rows]
        return {"n": len(values), "median_ms": percentile(values, 50), "p90_ms": percentile(values, 90),
                "values": values}

    # ── 읽기 : 진단 탭 ──────────────────────────────────────
    def hold_reasons(self, days: int = 7) -> list[dict]:
        return self._rows("SELECT i.code, COUNT(*) AS n FROM event_issues i JOIN events e USING(event_id) "
                          "WHERE e.status='HOLD' AND e.ts_utc >= datetime('now', ?) GROUP BY i.code ORDER BY n DESC",
                          (f"-{int(days)} days",))

    def confidence(self, days: int = 7) -> dict[str, dict]:
        """판정(PASS/NG 확정)에 쓰인 검출의 confidence 만. 무시된 검출은 안 들어간다."""
        sql = ("SELECT json_extract(d.value,'$.class_name') AS cls, json_extract(d.value,'$.confidence') AS conf "
               "FROM events e, json_each(e.observed_json) h, json_each(h.value, ?) d "
               "WHERE e.status IN ('PASS','NG') AND e.observed_json IS NOT NULL AND e.ts_utc >= datetime('now', ?)")
        buckets: dict[str, list[float]] = {}
        for slot in ("$.bolt", "$.part"):
            for r in self._rows(sql, (slot, f"-{int(days)} days")):
                if r["cls"] is not None and r["conf"] is not None:
                    buckets.setdefault(r["cls"], []).append(float(r["conf"]))
        return {cls: {"n": len(v), "median": percentile(v, 50), "p10": percentile(v, 10), "p90": percentile(v, 90)}
                for cls, v in sorted(buckets.items())}

    def metrics(self, hours: int = 1, run_id: int | None = None) -> list[dict]:
        where, params = ["bucket_utc >= datetime('now', ?)"], [f"-{int(hours)} hours"]
        if run_id is not None:
            where.append("run_id=?"); params.append(run_id)
        return self._rows(f"SELECT * FROM metrics WHERE {' AND '.join(where)} ORDER BY bucket_utc", params)

    def close(self) -> None:
        self.flush_metrics()
        with self._lock:
            self._con.close()
