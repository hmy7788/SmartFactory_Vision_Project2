"""파이프라인 — 소스 → 코어(InspectionService) → 저장(Store) → 화면(payload).

코어는 건드리지 않는다. 여기서 하는 일:
  1. 프레임마다 service.update()
  2. Store 에 변화만 기록 (record 는 events 없으면 0)
  3. 화면이 그릴 payload(JSON) 로 바꿔 콜백으로 넘김
  4. 버튼 명령(레시피 선택 · 새 작업 · 작업 완료)을 프레임 사이에 처리

코어에 없는 두 가지를 여기서 보탠다:
  - HOLD(각도 초과) 때의 Mother 각도 — geometry 가 비어서 코어는 모른다. 검출로 major_axis() 를 한 번 더 부른다.
  - 원본 검출 목록 — Snapshot 에는 없다. 진단 탭의 confidence 박스는 이걸 쓴다.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import asdict
from math import degrees
from pathlib import Path
from typing import Callable

from src.app.inspection_service import InspectionService
from src.contracts.inspection import Status
from src.geometry.mother_frame import major_axis
from src.process.recipe import load_recipe

from web.source import now_ms
from web.store import Store


def list_recipes(recipe_dirs) -> list[dict]:
    """레시피 폴더(들) 의 *.json. 뒤 폴더가 앞 폴더를 덮는다 — MES 가 내려준 레시피(data/mes_recipes) 가 로컬 것보다 우선."""
    dirs = [recipe_dirs] if isinstance(recipe_dirs, (str, Path)) else list(recipe_dirs)
    found: dict[str, dict] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            found[data["recipe_id"]] = {"recipe_id": data["recipe_id"], "placements": data["placements"], "file": path.name,
                                        "path": str(path), "version": data.get("version"), "source": data.get("source", "local")}
    return [found[k] for k in sorted(found)]


def _jsonable(obj):
    """Snapshot 안의 tuple·int 키·Enum 을 JSON 으로. dict 의 int 키는 문자열이 된다 (holes: "1".."5")."""
    if hasattr(obj, "value") and not isinstance(obj, (int, float)):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class Pipeline:
    def __init__(self, config: dict, recipe_dir: Path, store: Store, source_factory: Callable,
                 recipe_id: str, on_payload: Callable[[dict, bytes | None], None], model_file: str = "demo"):
        self.config, self.store = config, store
        self.recipe_dirs = [Path(recipe_dir)] if isinstance(recipe_dir, (str, Path)) else [Path(d) for d in recipe_dir]
        self.recipe_dir = self.recipe_dirs[0]
        self.recipes = {r["recipe_id"]: r for r in list_recipes(self.recipe_dirs)}
        if recipe_id not in self.recipes:
            raise KeyError(f"unknown recipe {recipe_id}; have {sorted(self.recipes)}")
        self.recipe = load_recipe(self.recipes[recipe_id]["path"])
        self.mes = None                             # web/mes_link.MesLink — 붙이면 작업지시가 레시피·수량을 정한다
        self.service = InspectionService(config, self.recipe)
        self.source = source_factory(self.recipe, config)
        self.on_payload = on_payload
        self.run_id = store.open_run(model_file, config)
        self.product_id: int | None = None
        self.last_payload: dict | None = None
        self.last_snapshot = None
        self.events: list[dict] = []                # 이 제품의 이벤트 (진단 탭 실시간 목록)
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="pipeline", daemon=True)
        self._last_ts: int | None = None
        self._fps_window: list[float] = []

    # ── 명령 (웹 스레드에서 호출) ──
    def refresh_recipes(self) -> list[dict]:
        """config/recipes/*.json 을 다시 읽는다. 서버를 켠 뒤 추가한 레시피도 재시작 없이 쓰기 위해.
        프레임마다 읽지 않고 레시피 탭을 열 때와 레시피를 고를 때만 부른다 (그때만 바뀔 수 있으니까)."""
        found = list_recipes(self.recipe_dirs)
        self.recipes = {r["recipe_id"]: r for r in found}
        return found

    def attach_mes(self, link) -> None:
        """MES 연동. 작업지시가 오면(다른 스레드) 명령 큐로 넘겨 프레임 사이에 적용한다."""
        self.mes = link
        link.on_work_order = lambda wo: self._commands.put(("workorder", wo))

    def select_recipe(self, recipe_id: str) -> None:
        if self.mes is not None:                    # 레시피는 작업지시가 정한다 — 작업자가 고르는 것 자체가 실수의 원인
            raise PermissionError("MES 연동 중에는 레시피를 작업지시가 정합니다")
        self.refresh_recipes()
        if recipe_id not in self.recipes:
            raise KeyError(recipe_id)
        self._commands.put(("recipe", recipe_id))

    def reset(self) -> None:
        self._commands.put(("reset", None))

    def complete(self) -> dict:
        """PASS 확정 상태에서만 허용. 아니면 이유를 돌려주고 아무것도 하지 않는다."""
        if self.mes is not None:
            ok, reason = self.mes.can_complete()
            if not ok:
                return {"ok": False, "reason": reason}
        snap = self.last_snapshot
        if snap is None or snap.status is not Status.PASS or not snap.stable:
            return {"ok": False, "reason": "PASS 확정 상태에서만 완료할 수 있습니다",
                    "status": snap.status.value if snap else None}
        done = threading.Event(); box: dict = {}
        self._commands.put(("complete", (done, box)))
        done.wait(timeout=5)
        return box or {"ok": False, "reason": "timeout"}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        if self._stop.is_set():                     # 두 번 불려도(서버 종료 + 테스트 정리) 같은 제품을 두 번 닫지 않게
            return
        self._stop.set()
        self._thread.join(timeout=3)
        if self.product_id is not None:
            self.store.close_product(self.product_id, now_ms(), result="ABANDONED")
        self.store.close_run(self.run_id)

    # ── 루프 ──
    def _new_product(self, first_ts: int) -> None:
        self.product_id = self.store.open_product(self.run_id, self.recipe.recipe_id, first_ts)
        self.events = []

    def _apply_commands(self, ts: int) -> None:
        while True:
            try:
                cmd, arg = self._commands.get_nowait()
            except queue.Empty:
                return
            if cmd == "recipe":
                self.recipe = load_recipe(self.recipes[arg]["path"])
                if self.product_id is not None:
                    self.store.close_product(self.product_id, ts, result="ABANDONED")
                self.service.reset(self.recipe); self.source.reset(self.recipe); self._new_product(ts)
            elif cmd == "reset":
                if self.product_id is not None:
                    self.store.close_product(self.product_id, ts, result="ABANDONED")
                self.service.reset(); self.source.reset(self.recipe); self._new_product(ts)
            elif cmd == "workorder":                   # MES 작업지시 적용(dict) / 취소(None). 열린 제품은 중단 처리
                if self.product_id is not None:
                    self.store.close_product(self.product_id, ts, result="ABANDONED")
                if arg is not None:
                    self.refresh_recipes()
                    self.recipe = load_recipe(self.recipes[arg["recipe_id"]]["path"])
                    self.service.reset(self.recipe)
                else:
                    self.service.reset()
                self.source.reset(self.recipe); self._new_product(ts)
            elif cmd == "complete":
                done, box = arg
                try:
                    summary = self.store.close_product(self.product_id, ts, result="COMPLETED")
                    if self.mes is not None:           # 수량 +1, result 를 outbox 로 (보내기는 mes 스레드가)
                        self.mes.product_completed(summary, self.store.ng_codes(self.product_id))
                    box.update({"ok": True, "product": summary})
                    self.service.reset(); self.source.reset(self.recipe); self._new_product(ts)
                except Exception as error:               # 화면에 이유를 돌려준다. 루프는 죽지 않는다.
                    box.update({"ok": False, "reason": str(error)})
                finally:
                    done.set()

    def _loop(self) -> None:
        for frame, jpeg in self.source.frames():
            if self._stop.is_set():
                break
            t0 = time.perf_counter()
            if self.product_id is None:
                self._new_product(frame.timestamp_ms)
            self._apply_commands(frame.timestamp_ms)
            snapshot = self.service.update(frame)
            mothers = [d for d in frame.detections if d.class_name == "mother_part"]
            angle = degrees(major_axis(mothers[0])[2]) if len(mothers) == 1 else None
            gap = (frame.timestamp_ms - self._last_ts) if self._last_ts is not None else None
            self._last_ts = frame.timestamp_ms
            written = self.store.record(self.product_id, snapshot, mother_angle_deg=angle,
                                        latency_ms=now_ms() - int(frame.timestamp_ms))
            total_ms = (time.perf_counter() - t0) * 1000
            self.store.frame(self.run_id, infer_ms=getattr(self.source, "infer_ms", None) or 0.0, total_ms=total_ms, gap_ms=gap,
                             hold=snapshot.candidate.status is Status.HOLD)
            self._fps_window = (self._fps_window + [time.perf_counter()])[-30:]
            fps = ((len(self._fps_window) - 1) / (self._fps_window[-1] - self._fps_window[0])
                   if len(self._fps_window) > 1 and self._fps_window[-1] > self._fps_window[0] else 0.0)
            if written:
                for ev in snapshot.events:
                    self.events.append(self._event_row(ev))
                self.events = self.events[-50:]
            self.last_snapshot = snapshot
            self.last_payload = self._payload(frame, snapshot, angle, gap, total_ms, fps)
            self.on_payload(self.last_payload, jpeg)

    def _event_row(self, ev: dict) -> dict:
        cand = ev["candidate"]
        return {"seq": ev["event_id"], "ts_ms": ev["timestamp_ms"], "event_type": ev["event_type"],
                "phase": _jsonable(ev["phase"]), "evaluated_phase": _jsonable(ev["from_phase"]),
                "status": _jsonable(ev["status"]), "candidate_status": _jsonable(cand["status"]),
                "issues": _jsonable(cand["issues"])}

    def _payload(self, frame, snapshot, angle, gap, total_ms, fps) -> dict:
        return {
            "type": "snapshot",
            "frame_id": frame.frame_id, "ts_ms": frame.timestamp_ms,
            "frame_size": list(self.source.frame_size), "has_video": self.source.has_video,
            "recipe": self.recipes[self.recipe.recipe_id],
            "recipes": sorted(self.recipes),
            "run_id": self.run_id, "product_id": self.product_id,
            "model": getattr(self, "model_label", None),                # 어떤 가중치로 돌고 있는지 (모델 비교할 때)
            "phase": snapshot.phase.value, "evaluated_phase": snapshot.evaluated_phase.value,
            "status": snapshot.status.value, "stable": snapshot.stable,
            "candidate": _jsonable(asdict(snapshot.candidate)),
            "confirmed": _jsonable(asdict(snapshot.confirmed)) if snapshot.confirmed else None,
            "materials": _jsonable(snapshot.materials), "observed": _jsonable(snapshot.observed),
            "geometry": _jsonable(snapshot.geometry),
            "detections": [_jsonable(asdict(d)) for d in frame.detections],
            "mother_angle_deg": angle,
            "calibration_status": snapshot.calibration_status,
            "source_error": getattr(self.source, "last_error", None),     # 카메라·모델 쪽 마지막 오류 (없으면 null)
            "video_at_end": bool(getattr(self.source, "at_end", False)),
            "mes": self.mes.view() if self.mes is not None else None,   # 작업지시 · 브로커 연결 · 못 보낸 건수  # --video: 영상이 끝나 마지막 장면을 유지 중
            "timing": {"gap_ms": gap, "total_ms": round(total_ms, 1), "fps": round(fps, 1),
                       "infer_ms": getattr(self.source, "infer_ms", None),          # 카메라 모드: 마지막 추론 시간
                       "result_age_ms": getattr(self.source, "result_age_ms", None),  # 화면에 붙은 판정이 몇 ms 전 것인지
                       "max_frame_gap_ms": self.config["max_frame_gap_ms"],
                       "stable_ms": self.config["stable_duration_ms"],
                       "material_stable_ms": self.config["material_stable_duration_ms"],
                       "max_angle_deg": self.config["max_mother_angle_deg"]},
            "events": self.events[-12:],
        }
