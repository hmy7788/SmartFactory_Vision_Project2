"""[작업 완료] 뒤 완성품 반출 대기 (web/pipeline.py) — 카메라 없이 장면을 바꿔 가며 확인한다.

09-28 시연: 레시피1 을 끝내고 [작업 완료] 를 누르면 작업대에 남은 완성품의 부품을 재료 확인(화면 전체 개수 세기) 이
'재료' 로 세어, 다음 레시피1 이 재료 확인 없이 바로 조립 → PASS 가 되어 버렸다.
이제는 완성품을 내리거나(Mother 가 안 보임) 그 자리에서 전부 분해해야(Mother 에 아무것도 안 꽂힘) 다음 재료 확인이 열린다.
"""
import tempfile
import time
import unittest
from pathlib import Path

from src.app.config import load_config
from src.contracts.detections import DetectionFrame
from web.pipeline import Pipeline
from web.source import DemoSource
from web.store import Store

ROOT = Path(__file__).resolve().parents[1]


class SceneSource:
    """테스트가 scene(검출 목록) 을 바꾸면 다음 프레임부터 그 장면. 시각은 프레임마다 50ms 씩 — 실제 시간과 무관해 결정적이다."""
    frame_size = (1200, 900)
    has_video = False
    STEP_MS = 50

    def __init__(self, recipe, config):
        self.geo = DemoSource(recipe, config)        # 검출을 만드는 기하(Mother·꽂힌 부품·흩어 놓은 재료) 만 빌려 쓴다
        self.scene = []
        self.frame_id, self.ts = 0, 1_000_000

    def reset(self, recipe):
        self.geo.reset(recipe)

    # 장면
    def materials(self):          # 재료 확인용: Mother + Mother 에서 떨어져 흩어 놓은 볼트·파트
        return [self.geo._mother()] + self.geo._scattered()

    def assembled(self):          # 완성품: 레시피대로 전부 꽂힌 Mother
        return [self.geo._mother()] + [d for p in self.geo.recipe.placements for d in self.geo._placed(p)]

    def frames(self):
        while True:
            self.frame_id += 1
            self.ts += self.STEP_MS
            yield DetectionFrame(self.frame_id, self.ts, tuple(self.scene)), None
            time.sleep(0.002)


class ClearWaitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = load_config(ROOT / "config/mvp.json")
        self.store = Store(Path(self.tmp.name) / "t.db", max_frame_gap_ms=self.config["max_frame_gap_ms"])
        self.sources = []

        def factory(recipe, cfg):
            src = SceneSource(recipe, cfg); self.sources.append(src); return src

        self.p = Pipeline(self.config, ROOT / "config/recipes", self.store, factory, "recipe_1", on_payload=lambda p, j: None)
        self.src = self.sources[0]

    def tearDown(self):
        if self.p._thread.ident is not None:            # 시작한 테스트만 (단위 테스트는 루프 없이 직접 부른다)
            self.p.stop()
        self.store.close(); self.tmp.cleanup()

    def wait(self, pred, seconds=10):
        t0 = time.time()
        while time.time() - t0 < seconds:
            s = self.p.last_payload
            if s is not None and pred(s):
                return s
            time.sleep(0.005)
        s = self.p.last_payload or {}
        self.fail(f"timeout; last {s.get('phase')} {s.get('status')} await={s.get('await_clear')} product={s.get('product_id')}")

    def frames_pass(self, n):
        """파이프라인이 프레임 n 장을 더 처리할 때까지 (합성 시각 n*50ms)."""
        start = self.p.last_payload["frame_id"]
        return self.wait(lambda s: s["frame_id"] >= start + n)

    def build_one(self):
        """재료 확인 → 조립 → PASS → [작업 완료]."""
        self.src.scene = self.src.materials()
        self.wait(lambda s: s["phase"] == "ASSEMBLING" and s["await_clear"] is None)
        self.src.scene = self.src.assembled()
        self.wait(lambda s: s["status"] == "PASS" and s["stable"])
        r = self.p.complete()
        self.assertTrue(r["ok"], r)

    def test_finished_product_left_on_table_is_not_counted_as_materials(self):
        self.p.require_clear = True
        self.p.start()
        self.build_one()
        s = self.wait(lambda s: s["await_clear"] is not None)
        self.assertIsNone(s["product_id"])
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        # 완성품을 그대로 두고 3초(재료 1초 + 조립 0.4초 안정보다 훨씬 김) — 예전엔 여기서 다시 PASS 가 됐다
        s = self.frames_pass(60)
        self.assertIsNotNone(s["await_clear"])
        self.assertEqual((s["phase"], s["status"]), ("CHECK_MATERIALS", "IN_PROGRESS"))
        self.assertEqual(s["await_clear"]["attached"], ["bolt_1", "bolt_2", "part_2hole", "part_3hole"])
        refused = self.p.complete()
        self.assertFalse(refused["ok"])
        self.assertIn("완성품", refused["reason"])
        self.p.reset()                                   # [새 작업] 도 반출 대기를 건너뛰지 못한다
        self.assertIsNotNone(self.frames_pass(10)["await_clear"])
        # 완성품을 내린다 → 1초 뒤 새 제품의 재료 확인
        self.src.scene = []
        s = self.wait(lambda s: s["await_clear"] is None)
        self.assertIsNotNone(s["product_id"])
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        self.assertEqual([h["result"] for h in self.store.history()], ["COMPLETED"])   # 두 번 세지 않았고, 대기 중 [새 작업] 도 흔적이 없다
        # 다음 재료를 놓으면 평소처럼 넘어간다
        self.src.scene = self.src.materials()
        self.wait(lambda s: s["phase"] == "ASSEMBLING")

    def test_disassembling_in_place_also_ends_the_wait(self):
        self.p.require_clear = True
        self.p.start()
        self.build_one()
        self.wait(lambda s: s["await_clear"] is not None)
        self.src.scene = self.src.materials()            # Mother 는 그대로, 볼트·파트를 전부 빼서 옆에 펼쳐 놓았다
        s = self.wait(lambda s: s["await_clear"] is None)
        self.assertEqual(s["phase"], "CHECK_MATERIALS")
        self.wait(lambda s: s["phase"] == "ASSEMBLING")  # 펼쳐 놓은 재료로 재료 확인 → 조립
        self.src.scene = self.src.assembled()
        self.wait(lambda s: s["status"] == "PASS" and s["stable"])
        self.assertTrue(self.p.complete()["ok"])
        self.assertEqual([h["result"] for h in self.store.history()], ["COMPLETED", "COMPLETED"])

    def test_without_clear_wait_next_product_starts_at_once(self):
        """영상·데모(require_clear=False) 는 예전 그대로: [작업 완료] 즉시 다음 제품."""
        self.p.start()
        self.build_one()
        s = self.frames_pass(2)
        self.assertIsNone(s["await_clear"])
        self.assertIsNotNone(s["product_id"])

    def test_wait_needs_a_continuous_clear_view(self):
        """손이 가려 한두 프레임 Mother 가 안 보여도 끝나지 않는다: 연달아 clear_ms 이상 · clear_min_frames 장 이상 비어야 한다."""
        p, src = self.p, self.src
        p.require_clear = True
        p._start_await_clear()
        ts = [5_000]

        def step(scene, dt=100):
            ts[0] += dt
            return p._await_clear_step(DetectionFrame(ts[0], ts[0], tuple(scene)))

        done = src.assembled()
        for _ in range(3):                               # 900ms 비고 → 다시 완성품: 처음부터 다시 센다
            self.assertTrue(all(step([]) for _ in range(9)))
            self.assertTrue(step(done))
        self.assertTrue(step([], dt=5000))               # 첫 빈 프레임 (시간이 많이 지나도 한 장으로는 안 된다)
        self.assertTrue(step([], dt=5000))
        self.assertFalse(step([], dt=5000))              # 세 장째 · 1초 이상 → 끝
        self.assertFalse(p.awaiting_clear)
        self.assertIsNotNone(p.product_id)

    def test_unjudgeable_frames_keep_waiting(self):
        """카메라 입력 없음 · Mother 두 개 · Mother 에 걸친 부품 은 '빈 작업대' 가 아니다."""
        p, src = self.p, self.src
        p._start_await_clear()
        m = src.geo._mother()
        self.assertEqual(p._table_clear(DetectionFrame(1, 1, (), input_valid=False))[0], False)
        second = type(m)("m2", "mother_part", 0.9, (600, 300), 1000, 160, 0.0)
        self.assertEqual(p._table_clear(DetectionFrame(2, 2, (m, second)))[0], False)
        lying = type(m)("x", "part_3hole", 0.9, (600, 700), 500, 90, 0.0)      # Mother 위에 가로로 걸쳐 놓은 파트 (자리에는 안 꽂힘)
        self.assertEqual(p._table_clear(DetectionFrame(3, 3, (m, lying)))[0], False)
        self.assertEqual(p._table_clear(DetectionFrame(4, 4, tuple(src.materials()))), (True, {"mother": True, "attached": []}))
        self.assertEqual(p._table_clear(DetectionFrame(5, 5, ())), (True, {"mother": False, "attached": []}))


class ServerFlagTests(unittest.TestCase):
    def test_default_is_live_camera_only(self):
        try:
            from web.server import build, parse
        except (ImportError, RuntimeError):
            self.skipTest("starlette not installed")
        with tempfile.TemporaryDirectory() as d:
            _, pipeline, store, _ = build(parse(["--db", str(Path(d) / "a.db")]))
            self.assertFalse(pipeline.require_clear)                      # 데모
            _, pipeline2, store2, _ = build(parse(["--db", str(Path(d) / "b.db"), "--clear-wait"]))
            self.assertTrue(pipeline2.require_clear)
            for s in (store, store2):
                s.close() if hasattr(s, "close") else None
        self.assertIs(parse(["--no-clear-wait"]).clear_wait, False)
        self.assertIsNone(parse([]).clear_wait)


if __name__ == "__main__":
    unittest.main()
