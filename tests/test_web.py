"""web/ — 소스·파이프라인·서버를 카메라·모델 없이 검증한다.

starlette 의 TestClient 로 HTTP 와 WebSocket 을 프로세스 안에서 돈다 (uvicorn 불필요).
DemoSource 는 fps 를 높여 시나리오를 빨리 돌린다.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.inspection import Status
from src.process.recipe import load_recipe
from web.source import CameraSource, DemoSource, JsonlSource, demo_config, now_ms
from web.store import Store

try:
    from starlette.testclient import TestClient
    from web.server import build, parse
    HAVE_STARLETTE = True
except ImportError:              # 팀 환경에 fastapi/starlette 가 없으면 서버 테스트만 건너뛴다
    HAVE_STARLETTE = False

ROOT = Path(__file__).resolve().parents[1]


def run_until(service, source, pred, seconds=15):
    """소스 프레임을 코어에 넣으며 pred(snapshot) 이 참이 될 때까지. 안 되면 마지막 snapshot."""
    t0, last = time.time(), None
    for frame, _ in source.frames():
        last = service.update(frame)
        if pred(last) or time.time() - t0 > seconds:
            return last
    return last


class DemoSourceTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config/mvp.json")

    def test_every_recipe_reaches_pass_through_ng_and_hold(self):
        for name in ("recipe_1", "recipe_2", "recipe_3"):
            recipe = load_recipe(ROOT / f"config/recipes/{name}.json")
            config = demo_config(self.config, 4)          # 배속 4: 단계 길이와 안정화 창을 같이 1/4
            service, source = InspectionService(config, recipe), DemoSource(recipe, config, fps=200, speed=4)
            seen = set()
            def watch(s):
                seen.add((s.phase.value, s.status.value)); return False
            run_until(service, source, watch, seconds=6)
            self.assertIn(("CHECK_MATERIALS", "NG"), seen, name)
            self.assertIn(("ASSEMBLING", "NG"), seen, name)
            self.assertIn(("ASSEMBLING", "HOLD"), seen, name)
            self.assertIn(("ASSEMBLING", "PASS"), seen, name)

    def test_reset_restarts_scenario(self):
        recipe = load_recipe(ROOT / "config/recipes/recipe_1.json")
        source = DemoSource(recipe, self.config, fps=200)
        source.stage_i = 5
        source.reset(recipe)
        self.assertEqual(source.stage_i, 0)

    def test_timestamps_are_monotonic(self):
        recipe = load_recipe(ROOT / "config/recipes/recipe_3.json")
        source = DemoSource(recipe, self.config, fps=500)
        ts = [fr[0].timestamp_ms for fr, _ in zip(source.frames(), range(20))]
        self.assertEqual(ts, sorted(ts))

    def test_jsonl_source_replays_and_relabels_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.jsonl"
            rows = [{"frame_id": i, "timestamp_ms": i * 10, "input_valid": True,
                     "detections": [{"detection_id": "m", "class_name": "mother_part", "confidence": 0.9,
                                     "center_xy": [600, 700], "width": 1000, "height": 160, "angle_rad": 0}]} for i in range(3)]
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            frames = [fr[0] for fr, _ in zip(JsonlSource(path, loop=False).frames(), range(3))]
            self.assertEqual([f.frame_id for f in frames], [1, 2, 3])
            self.assertTrue(frames[0].timestamp_ms <= frames[1].timestamp_ms <= frames[2].timestamp_ms)
            self.assertEqual(frames[0].detections[0].class_name, "mother_part")


# ── 가짜 카메라 · 가짜 ultralytics 결과 (가중치 없이 카메라 경로 전체를 돈다) ──
class _T:
    """ultralytics 텐서 흉내: .cpu().tolist() 만 있으면 어댑터가 만족한다."""
    def __init__(self, rows): self.rows = rows
    def cpu(self): return self
    def tolist(self): return self.rows


class _Obb:
    def __init__(self, xywhr, cls, conf): self.xywhr, self.cls, self.conf = _T(xywhr), _T(cls), _T(conf)


class _Result:
    """model.predict(img)[0] 이 돌려주는 Results 흉내. names 는 학습 때 쓴 한글 클래스."""
    names = {0: "나무_5구멍", 1: "볼트_노랑", 2: "볼트_주황", 3: "나무_2구멍", 4: "나무_3구멍"}
    def __init__(self, obb): self.obb = obb


class _Model:
    def __init__(self, result, delay=0.0): self.result, self.delay, self.calls = result, delay, 0
    def predict(self, img, **kw):
        self.calls += 1; time.sleep(self.delay); return [self.result]


class _Cap:
    def __init__(self, frames): self.frames, self.i, self.released = frames, 0, False
    def read(self):
        fr = self.frames[min(self.i, len(self.frames) - 1)]; self.i += 1
        return (fr is not None), fr
    def release(self): self.released = True


def _img(w=640, h=480):
    import numpy as np
    return np.zeros((h, w, 3), dtype=np.uint8)


class CameraSourceTests(unittest.TestCase):
    def setUp(self):
        self.mapping = ROOT / "config/class_mapping.json"

    def test_korean_classes_mapped_and_timestamp_is_capture_time(self):
        result = _Result(_Obb([[600, 700, 1000, 160, 0.0], [200, 700, 80, 80, 0.0]], [0, 1], [0.97, 0.9]))
        model = _Model(result, delay=0.05)                       # 추론 50ms
        src = CameraSource(capture=_Cap([_img()]), model=model, mapping_path=self.mapping)
        (frame, jpeg), = [next(src.frames())]
        self.assertEqual([d.class_name for d in frame.detections], ["mother_part", "bolt_1"])   # 한글 → 영문
        self.assertTrue(frame.input_valid)
        self.assertLess(now_ms() - frame.timestamp_ms, 200)     # 캡처 시각이지 추론 뒤가 아니다
        self.assertEqual(src.frame_size, (640, 480))            # 실제 캡처 크기로 바뀐다 (오버레이 좌표계)
        self.assertTrue(jpeg is None or jpeg[:2] == b"\xff\xd8")  # cv2 있으면 JPEG

    def test_camera_read_failure_yields_invalid_frame_not_crash(self):
        result = _Result(_Obb([], [], []))
        src = CameraSource(capture=_Cap([None, _img()]), model=_Model(result), mapping_path=self.mapping)
        it = src.frames()
        f1, _ = next(it)
        self.assertFalse(f1.input_valid); self.assertEqual(src.last_error, "camera read failed")
        f2, _ = next(it)
        self.assertTrue(f2.input_valid); self.assertIsNone(src.last_error)
        self.assertLess(f1.frame_id, f2.frame_id)

    def test_unknown_class_name_becomes_hold_frame(self):
        bad = _Result(_Obb([[10, 10, 5, 5, 0]], [0], [0.9])); bad.names = {0: "너트_파랑"}   # 제외된 클래스
        src = CameraSource(capture=_Cap([_img()]), model=_Model(bad), mapping_path=self.mapping)
        frame, _ = next(src.frames())
        self.assertFalse(frame.input_valid)
        self.assertIn("ValueError", src.last_error)

    def test_core_runs_on_camera_frames(self):
        """가짜 카메라 프레임이 코어까지 통과해 재료 판정을 낸다."""
        rows = [[600, 700, 1000, 160, 0.0], [120, 120, 80, 80, 0.0], [520, 120, 80, 80, 0.0],
                [330, 120, 320, 90, 0.0], [730, 120, 500, 90, 0.0]]
        result = _Result(_Obb(rows, [0, 1, 2, 3, 4], [0.97, 0.9, 0.9, 0.88, 0.88]))   # recipe_1 재료 정확히
        src = CameraSource(capture=_Cap([_img(1200, 900)]), model=_Model(result), mapping_path=self.mapping)
        config = demo_config(load_config(ROOT / "config/mvp.json"), 4)
        service = InspectionService(config, load_recipe(ROOT / "config/recipes/recipe_1.json"))
        last = run_until(service, src, lambda s: s.phase.value == "ASSEMBLING", seconds=5)
        self.assertEqual(last.phase.value, "ASSEMBLING")        # 재료 READY 가 유지되어 조립 단계로


@unittest.skipUnless(HAVE_STARLETTE, "starlette not installed")
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        args = parse(["--db", str(Path(self.tmp.name) / "t.db"), "--fps", "60", "--speed", "4"])
        self.app, self.pipeline, self.store, self.hub = build(args)
        self.pipeline.start()
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)      # lifespan shutdown → pipeline.stop()
        self.tmp.cleanup()

    def wait(self, pred, seconds=15):
        t0 = time.time()
        while time.time() - t0 < seconds:
            s = self.client.get("/api/state").json()
            if pred(s):
                return s
            time.sleep(0.05)
        self.fail(f"timeout waiting; last={self.client.get('/api/state').json().get('status')}")

    def test_payload_contract(self):
        s = self.wait(lambda s: s.get("frame_id", 0) > 3)
        for key in ("phase", "evaluated_phase", "status", "stable", "candidate", "materials", "observed",
                    "geometry", "detections", "recipe", "recipes", "product_id", "run_id", "timing", "frame_size"):
            self.assertIn(key, s)
        self.assertEqual(s["recipe"]["recipe_id"], "recipe_1")
        self.assertIsInstance(s["detections"], list)

    def test_scenario_and_complete(self):
        self.wait(lambda s: s["phase"] == "CHECK_MATERIALS" and s["status"] == "NG")
        self.wait(lambda s: s["phase"] == "ASSEMBLING" and s["status"] == "NG" and s["stable"])
        # NG 상태에서 완료는 거부된다 (409)
        r = self.client.post("/api/complete")
        self.assertEqual(r.status_code, 409)
        hold = self.wait(lambda s: s["status"] == "HOLD" and s["phase"] == "ASSEMBLING")
        self.assertEqual(hold["geometry"], {})                      # 각도 초과 → geometry 없음
        self.assertAlmostEqual(abs(hold["mother_angle_deg"]), 26.0, places=0)   # 파이프라인이 각도를 보탠다
        self.wait(lambda s: s["status"] == "PASS" and s["stable"])
        r = self.client.post("/api/complete")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        summary = r.json()["product"]
        self.assertEqual((summary["ng_count"], summary["material_ng_count"], summary["hold_count"], summary["first_pass"]), (1, 1, 1, 0))
        hist = self.client.get("/api/history").json()
        self.assertEqual(len(hist), 1)
        tl = self.client.get(f"/api/timeline/{hist[0]['product_id']}").json()
        self.assertEqual(tl[-1]["event_type"], "PRODUCT_COMPLETED")
        self.assertTrue(any(e["event_type"] == "ASSEMBLY_STARTED" for e in tl))
        ana = self.client.get("/api/analytics?days=1").json()
        self.assertEqual(ana["pareto"][0]["code"], "WRONG_BOLT")
        diag = self.client.get("/api/diagnostics").json()
        self.assertEqual(diag["hold_reasons"][0]["code"], "MOTHER_ANGLE_OUT_OF_RANGE")

    def test_recipe_switch_and_reset(self):
        self.wait(lambda s: s.get("frame_id", 0) > 3)
        self.assertEqual(self.client.post("/api/recipe/recipe_2").status_code, 200)
        s = self.wait(lambda s: s["recipe"]["recipe_id"] == "recipe_2")
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        self.assertEqual(self.client.post("/api/recipe/nope").status_code, 404)
        before = s["product_id"]
        self.client.post("/api/reset")
        s = self.wait(lambda s: s["product_id"] != before)
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        self.assertGreaterEqual(len(self.client.get("/api/history?result=ABANDONED").json()), 1)

    def test_websocket_and_static(self):
        self.wait(lambda s: s.get("frame_id", 0) > 3)
        with self.client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            self.assertEqual(msg["type"], "snapshot")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/video").status_code, 404)      # 데모 소스는 영상이 없다


@unittest.skipUnless(HAVE_STARLETTE, "starlette not installed")
class RecipeHotAddTests(unittest.TestCase):
    """서버를 켠 뒤에 추가한 레시피 파일을 재시작 없이 고를 수 있어야 한다."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.TemporaryDirectory()
        self.rdir = Path(self.tmp.name) / "recipes"
        shutil.copytree(ROOT / "config/recipes", self.rdir)
        args = parse(["--db", str(Path(self.tmp.name) / "t.db"), "--recipe-dir", str(self.rdir), "--fps", "60", "--speed", "4"])
        self.app, self.pipeline, self.store, self.hub = build(args)
        self.pipeline.start()
        self.client = TestClient(self.app); self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None); self.tmp.cleanup()

    def test_recipe_file_added_after_start_is_selectable(self):
        t0 = time.time()
        while self.client.get("/api/state").json().get("frame_id", 0) < 3 and time.time() - t0 < 15:
            time.sleep(0.05)
        self.assertEqual(self.client.post("/api/recipe/recipe_9").status_code, 404)        # 아직 없다
        (self.rdir / "recipe_9.json").write_text(json.dumps({"recipe_id": "recipe_9", "placements": [
            {"mother_hole": 2, "bolt": "bolt_1", "part": "part_2hole"}]}), encoding="utf-8")
        ids = [r["recipe_id"] for r in self.client.get("/api/recipes").json()["recipes"]]
        self.assertIn("recipe_9", ids)                                                     # 레시피 탭에 보이고
        self.assertEqual(self.client.post("/api/recipe/recipe_9").status_code, 200)        # 고를 수 있고
        t0 = time.time()
        while time.time() - t0 < 15:
            s = self.client.get("/api/state").json()
            if s["recipe"]["recipe_id"] == "recipe_9":
                break
            time.sleep(0.05)
        self.assertEqual(s["recipe"]["recipe_id"], "recipe_9")
        self.assertIn("recipe_9", s["recipes"])                                            # 헤더 드롭다운에도


if __name__ == "__main__":
    unittest.main()
