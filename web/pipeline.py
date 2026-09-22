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


def list_recipes(recipe_dir: Path) -> list[dict]:
    out = []
    for path in sorted(recipe_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({"recipe_id": data["recipe_id"], "placements": data["placements"], "file": path.name})
    return out


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
        self.config, self.recipe_dir, self.store = config, Path(recipe_dir), store
        self.recipes = {r["recipe_id"]: r for r in list_recipes(self.recipe_dir)}
        if recipe_id not in self.recipes:
            raise KeyError(f"unknown recipe {recipe_id}; have {sorted(self.recipes)}")
        self.recipe = load_recipe(self.recipe_dir / self.recipes[recipe_id]["file"])
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
    def select_recipe(self, recipe_id: str) -> None:
        if recipe_id not in self.recipes:
            raise KeyError(recipe_id)
        self._commands.put(("recipe", recipe_id))

    def reset(self) -> None:
        self._commands.put(("reset", None))

    def complete(self) -> dict:
        """PASS 확정 상태에서만 허용. 아니면 이유를 돌려주고 아무것도 하지 않는다."""
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
                self.recipe = load_recipe(self.recipe_dir / self.recipes[arg]["file"])
                if self.product_id is not None:
                    self.store.close_product(self.product_id, ts, result="ABANDONED")
                self.service.reset(self.recipe); self.source.reset(self.recipe); self._new_product(ts)
            elif cmd == "reset":
                if self.product_id is not None:
                    self.store.close_product(self.product_id, ts, result="ABANDONED")
                self.service.reset(); self.source.reset(self.recipe); self._new_product(ts)
            elif cmd == "complete":
                done, box = arg
                try:
                    summary = self.store.close_product(self.product_id, ts, result="COMPLETED")
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
            self.store.frame(self.run_id, infer_ms=0.0, total_ms=total_ms, gap_ms=gap,
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
            "phase": snapshot.phase.value, "evaluated_phase": snapshot.evaluated_phase.value,
            "status": snapshot.status.value, "stable": snapshot.stable,
            "candidate": _jsonable(asdict(snapshot.candidate)),
            "confirmed": _jsonable(asdict(snapshot.confirmed)) if snapshot.confirmed else None,
            "materials": _jsonable(snapshot.materials), "observed": _jsonable(snapshot.observed),
            "geometry": _jsonable(snapshot.geometry),
            "detections": [_jsonable(asdict(d)) for d in frame.detections],
            "mother_angle_deg": angle,
            "calibration_status": snapshot.calibration_status,
            "timing": {"gap_ms": gap, "total_ms": round(total_ms, 1), "fps": round(fps, 1),
                       "max_frame_gap_ms": self.config["max_frame_gap_ms"],
                       "stable_ms": self.config["stable_duration_ms"],
                       "material_stable_ms": self.config["material_stable_duration_ms"],
                       "max_angle_deg": self.config["max_mother_angle_deg"]},
            "events": self.events[-12:],
        }
