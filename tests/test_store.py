"""web/store.py — 실제 코어(InspectionService) 출력을 그대로 넣어 검증한다.

합성 데모 흐름(scripts/demo_data.py): 부족 → 초과 NG → 정확 → 조립 시작 → 대기 → PASS →
H5 잉여 NG → 수정 PASS → Mother 유실 HOLD → 복귀 PASS.  가상 timestamp(100ms 간격).
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame
from src.contracts.inspection import Status
from src.process.recipe import load_recipe
from scripts.demo_data import demo_frames, mother, components
from web.store import Store, percentile, ASSEMBLY_STARTED, PRODUCT_COMPLETED, PRODUCT_ABANDONED

ROOT = Path(__file__).resolve().parents[1]


def run_demo(store, run_id, recipe_name="recipe_1"):
    """데모 흐름 전체를 코어에 넣고 Store 에 기록한 뒤 (product_id, 마지막 snapshot, 이벤트 수) 를 돌려준다."""
    config = load_config(ROOT / "config/mvp.json")
    recipe = load_recipe(ROOT / f"config/recipes/{recipe_name}.json")
    service = InspectionService(config, recipe)
    product = store.open_product(run_id, recipe.recipe_id, started_ms=0)
    written, last = 0, None
    for frame in demo_frames(recipe, config):
        last = service.update(frame)
        written += store.record(product, last, latency_ms=46)
        store.frame(run_id, infer_ms=40, total_ms=46, gap_ms=100, hold=last.candidate.status is Status.HOLD)
    return product, last, written


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")
        self.run = self.store.open_run("model/yolo_obb_parts.pt", load_config(ROOT / "config/mvp.json"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    # ── 스키마 ──
    def test_schema_and_foreign_keys(self):
        names = {r["name"] for r in self.store._rows("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"runs", "products", "events", "event_issues", "metrics"} <= names)
        self.assertEqual(self.store._one("PRAGMA foreign_keys")["foreign_keys"], 1)
        with self.assertRaises(sqlite3.IntegrityError):      # 고아 이벤트는 거부되어야 한다
            self.store._x("INSERT INTO events(product_id, core_seq, ts_ms, ts_utc, event_type, phase, "
                          "evaluated_phase, status, candidate_status, issues_json) "
                          "VALUES (999, 1, 0, '2026-01-01 00:00:00', 'STATUS_CHANGED', 'ASSEMBLING', "
                          "'ASSEMBLING', 'NG', 'NG', '[]')")

    # ── 쓰기 : 변화만 ──
    def test_record_writes_only_on_change(self):
        product, last, written = run_demo(self.store, self.run)
        self.assertEqual(last.status, Status.PASS)
        timeline = self.store.timeline(product)
        self.assertEqual(written, len(timeline))                       # 아직 닫기 전 — 닫기 이벤트 없음
        self.assertLess(written, 20)                                     # 66 프레임 → 이벤트는 한 자릿수
        kinds = [e["event_type"] for e in timeline]
        self.assertEqual(kinds.count(ASSEMBLY_STARTED), 1)
        statuses = [e["status"] for e in timeline]
        self.assertIn("NG", statuses); self.assertIn("HOLD", statuses); self.assertIn("PASS", statuses)
        # issues 가 펼쳐져 들어갔나 — H5 잉여 볼트
        rows = self.store._rows("SELECT code, hole_id, observed FROM event_issues WHERE code='UNEXPECTED_COMPONENT'")
        self.assertTrue(rows and rows[0]["hole_id"] == 5 and rows[0]["observed"] == "bolt_1")
        # 재료 초과도 코드 그대로
        self.assertTrue(self.store._rows("SELECT 1 FROM event_issues WHERE code='MATERIAL_EXCESS'"))
        # 이벤트에 mother pose 가 들어갔나 (조립 단계 이벤트)
        pose = self.store._one("SELECT mother_cx, mother_angle_deg FROM events WHERE status='PASS' LIMIT 1")
        self.assertAlmostEqual(pose["mother_cx"], 600.0); self.assertAlmostEqual(pose["mother_angle_deg"], 0.0)

    # ── 닫기 : 요약 계산 ──
    def test_close_product_summary(self):
        product, last, _ = run_demo(self.store, self.run)
        summary = self.store.close_product(product, closed_ms=last.timestamp_ms + 100)
        self.assertEqual(summary["result"], "COMPLETED")
        self.assertEqual(summary["ng_count"], 1)                 # H5 잉여 (조립)
        self.assertEqual(summary["material_ng_count"], 1)        # 재료 초과
        self.assertEqual(summary["hold_count"], 1)               # Mother 유실 (전환 프레임 HOLD 는 제외)
        self.assertEqual(summary["first_pass"], 0)
        self.assertIsNotNone(summary["materials_ok_ms"])
        self.assertEqual(summary["cycle_ms"], summary["materials_ms"] + summary["assembly_ms"])
        self.assertGreater(summary["assembly_ms"], summary["materials_ms"])
        # 닫기 이벤트가 타임라인 끝에 붙는다
        self.assertEqual(self.store.timeline(product)[-1]["event_type"], PRODUCT_COMPLETED)
        # 두 번 닫을 수 없다
        with self.assertRaises(ValueError):
            self.store.close_product(product, closed_ms=99999)

    def test_pass_events_are_not_products(self):
        product, last, _ = run_demo(self.store, self.run)
        passes = self.store._one("SELECT COUNT(*) AS n FROM events WHERE status='PASS'")["n"]
        self.assertGreaterEqual(passes, 3)                        # PASS 가 여러 번 확정되지만
        self.store.close_product(product, closed_ms=last.timestamp_ms + 100)
        self.assertEqual(len(self.store.history()), 1)            # 제품은 1대

    def test_abandon_and_reopen(self):
        p1 = self.store.open_product(self.run, "recipe_1", started_ms=0)
        p2 = self.store.open_product(self.run, "recipe_2", started_ms=5000)   # 새 작업 → 이전 제품 자동 ABANDONED
        rows = {r["product_id"]: r for r in self.store._rows("SELECT * FROM products")}
        self.assertEqual(rows[p1]["result"], "ABANDONED"); self.assertEqual(rows[p1]["cycle_ms"], 5000)
        self.assertEqual(rows[p1]["first_pass"], 0)
        self.assertEqual(rows[p2]["result"], "OPEN")
        self.assertEqual(self.store.timeline(p1)[-1]["event_type"], PRODUCT_ABANDONED)

    # ── 읽기 : 분석 쿼리가 실제 데이터로 돈다 ──
    def test_analytics_queries(self):
        for _ in range(2):
            product, last, _ = run_demo(self.store, self.run)
            self.store.close_product(product, closed_ms=last.timestamp_ms + 100)
        clean = self.store.open_product(self.run, "recipe_3", started_ms=0)     # NG 없는 제품 하나
        config = load_config(ROOT / "config/mvp.json"); recipe = load_recipe(ROOT / "config/recipes/recipe_3.json")
        service = InspectionService(config, recipe)
        t = 0
        far = lambda i, d: type(d)(d.detection_id, d.class_name, d.confidence, (150 + i * 220, 150), d.width, d.height, d.angle_rad)
        for k in range(14):                                                    # 재료 준비 1초
            t += 100
            self.store.record(clean, service.update(DetectionFrame(k, t, tuple([mother()] + [far(i, d) for i, d in enumerate(components(recipe, config))]))))
        for k in range(14, 22):                                                # 바로 정확한 조립
            t += 100
            self.store.record(clean, service.update(DetectionFrame(k, t, tuple([mother()] + components(recipe, config)))))
        summary = self.store.close_product(clean, closed_ms=t + 100)
        self.assertEqual(summary["first_pass"], 1)

        fpy = self.store.fpy(days=1)
        self.assertEqual(fpy["total"]["n"], 3)
        self.assertAlmostEqual(fpy["total"]["fpy"], 33.3, places=1)
        by = {r["recipe_id"]: r for r in fpy["by_recipe"]}
        self.assertEqual(by["recipe_1"]["fpy"], 0.0); self.assertEqual(by["recipe_3"]["fpy"], 100.0)

        pareto = self.store.pareto(days=1)
        self.assertEqual(pareto[0]["code"], "UNEXPECTED_COMPONENT"); self.assertEqual(pareto[-1]["cum_pct"], 100.0)
        self.assertEqual(self.store.heatmap(days=1)["recipe_1"][5], 2)
        rec = self.store.recovery(days=1)
        self.assertEqual(rec["n"], 2); self.assertGreater(rec["median_ms"], 0)
        self.assertEqual(self.store.hold_reasons(days=1)[0]["code"], "MOTHER_NOT_FOUND")
        conf = self.store.confidence(days=1)
        self.assertIn("bolt_1", conf); self.assertAlmostEqual(conf["bolt_1"]["median"], 0.99)
        cyc = self.store.cycle(days=1)
        self.assertEqual(cyc["recipe_1"]["cycle"]["n"], 2)
        hist = self.store.history(ng_only=True)
        self.assertEqual(len(hist), 2)

    # ── metrics 버킷 ──
    def test_metrics_buckets(self):
        for i in range(30):
            self.store.frame(self.run, infer_ms=40 + i, total_ms=45 + i, gap_ms=100, ts_utc="2026-09-22 05:31:00")
        for i in range(10):
            self.store.frame(self.run, infer_ms=90, total_ms=100, gap_ms=300, hold=True, ts_utc="2026-09-22 05:32:10")
        self.store.flush_metrics()
        rows = self.store._rows("SELECT * FROM metrics ORDER BY bucket_utc")
        self.assertEqual([r["bucket_utc"] for r in rows], ["2026-09-22 05:31:00", "2026-09-22 05:32:00"])
        self.assertEqual(rows[0]["frames"], 30); self.assertEqual(rows[0]["frame_gap_over"], 0)
        self.assertEqual(rows[1]["frame_gap_over"], 10); self.assertEqual(rows[1]["hold_frames"], 10)
        self.assertEqual(rows[0]["infer_ms_p50"], percentile([40 + i for i in range(30)], 50))

    def test_percentile(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertEqual(percentile([1, 2, 3, 4, 5], 90), 5)
        self.assertIsNone(percentile([], 50))


if __name__ == "__main__":
    unittest.main()
