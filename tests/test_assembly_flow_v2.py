"""Lenient hole assignment, drift following, evidence voting, alert and final verdict."""
import unittest
from dataclasses import replace
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.contracts.inspection import Phase, Status
from src.geometry.hole_assignment import HoleAssigner
from src.process.recipe import load_recipe
from scripts.demo_data import mother, components

ROOT = Path(__file__).resolve().parents[1]
STEP = 200          # demo Mother: 1000 px long, holes 0.2 apart


def shift(ds, dx, dy=0):
    return [replace(d, center_xy=(d.center_xy[0]+dx, d.center_xy[1]+dy)) for d in ds]


class Base(unittest.TestCase):
    pass_confirm_ms = 60000

    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        self.config["assembly"] = {"pass_confirm_ms": self.pass_confirm_ms}
        self.recipe = load_recipe(ROOT/"config/recipes/recipe_1.json")
        self.service = InspectionService(self.config, self.recipe)
        self.time, self.frame_id = -100, -1

    def tick(self, detections, delta=100):
        self.time += delta
        self.frame_id += 1
        return self.service.update(DetectionFrame(self.frame_id, self.time, tuple(detections)))

    def feed(self, detections, count):
        return [self.tick(detections) for _ in range(count)]

    def parts(self):
        return components(self.recipe, self.config)

    def to_assembly(self):
        inventory = [mother()]+[replace(d, center_xy=(100+i*200, 100)) for i, d in enumerate(self.parts())]
        self.feed(inventory, 11)
        self.assertEqual(self.feed([mother()], 11)[-1].phase, Phase.ASSEMBLING)

    def codes(self, snapshot):
        return [(i.code, i.hole_id) for i in snapshot.candidate.issues]


class AssignmentTests(Base):
    def geometry(self):
        self.to_assembly()
        return self.service.tracker.lock.geometry(self.config)

    def bolt(self, x, cls="bolt_1"):
        return OBBDetection("b", cls, .9, (x, 700), 80, 80, 0)

    def test_nearest_hole_is_lenient_but_boundary_is_not_guessed(self):
        geometry, assigner = self.geometry(), HoleAssigner(self.config)
        h1 = geometry["holes"][1][0]
        observed, ambiguous, _ = assigner.assign([self.bolt(h1+0.35*STEP)], geometry)
        self.assertEqual(len(observed[1]["bolt"]), 1)              # 35 % of spacing off: still H1
        assigner.reset()
        observed, ambiguous, _ = assigner.assign([self.bolt(h1+0.5*STEP)], geometry)
        self.assertEqual(ambiguous, ("b",))                          # midway: never H1 or H2 by guess
        self.assertFalse(observed[1]["bolt"] or observed[2]["bolt"])

    def test_sticky_assignment_and_clear_switch(self):
        geometry, assigner = self.geometry(), HoleAssigner(self.config)
        h1 = geometry["holes"][1][0]
        assigner.assign([self.bolt(h1+0.35*STEP)], geometry)
        observed, _, _ = assigner.assign([self.bolt(h1+0.55*STEP)], geometry)
        self.assertEqual(len(observed[1]["bolt"]), 1)              # wobble near boundary keeps H1
        observed, _, _ = assigner.assign([self.bolt(h1+0.78*STEP)], geometry)
        self.assertEqual(len(observed[2]["bolt"]), 1)              # clearly at H2 now

    def test_part_lying_across_mother_is_not_a_wrong_assembly(self):
        geometry, assigner = self.geometry(), HoleAssigner(self.config)
        lying = OBBDetection("p", "part_3hole", .9, (600, 700), 700, 180, 0)   # horizontal on top
        observed, ambiguous, _ = assigner.assign([lying], geometry)
        self.assertEqual(ambiguous, ("p",))

    def test_spare_far_away_ignored(self):
        geometry, assigner = self.geometry(), HoleAssigner(self.config)
        _, ambiguous, ignored = assigner.assign([OBBDetection("s", "bolt_1", .9, (1500, 100), 80, 80, 0)], geometry)
        self.assertEqual((ambiguous, ignored), ((), ("s",)))


class DriftTests(Base):
    def test_small_mother_nudge_still_passes(self):
        self.to_assembly()
        for dx in (10, 20, 30):                                      # Mother nudged 3 % in steps
            snapshot = self.feed(shift([mother()]+self.parts(), dx), 6)[-1]
            self.assertNotIn(("MOTHER_MOVING", 0), self.codes(snapshot))
        self.assertEqual(snapshot.status, Status.PASS)

    def test_parts_offset_while_mother_hidden_still_pass(self):
        self.to_assembly()
        snapshot = self.feed(shift(self.parts(), 60), 8)[-1]        # 0.3 spacing off, no Mother detection
        self.assertEqual(snapshot.status, Status.PASS)

    def test_seated_bolts_correct_the_grid(self):
        self.to_assembly()
        before = self.service.tracker.lock.geometry(self.config)["holes"][1][0]
        self.feed(shift(self.parts(), 40), 15)                       # Mother hidden, bolts 40 px right
        after = self.service.tracker.lock.geometry(self.config)["holes"][1][0]
        self.assertGreater(after-before, 30)


class EvidenceTests(Base):
    def test_single_frame_misclass_under_hand_ignored(self):
        self.to_assembly()
        self.feed([mother()]+self.parts(), 6)
        flicker = [replace(d, class_name="bolt_2") if d.detection_id == "b1" else d for d in self.parts()]
        snapshot = self.tick(flicker)                                # hand over Mother: low-weight frame
        self.assertEqual(snapshot.candidate.status, Status.PASS)
        self.assertEqual(self.feed([mother()]+self.parts(), 2)[-1].status, Status.PASS)

    def test_real_wrong_bolt_becomes_ng(self):
        self.to_assembly()
        wrong = [mother()]+[replace(d, class_name="bolt_2") if d.detection_id == "b1" else d for d in self.parts()]
        self.assertEqual(self.feed(wrong, 6)[-1].status, Status.NG)


class AlertAndResultTests(Base):
    pass_confirm_ms = 2000

    def test_red_alert_only_for_lasting_confirmed_ng(self):
        self.to_assembly()
        wrong = [mother()]+[replace(d, class_name="bolt_2") if d.detection_id == "b1" else d for d in self.parts()]
        snapshots = self.feed(wrong, 10)
        alerts = [s.alert for s in snapshots]
        self.assertEqual(alerts[:4], ["", "", "", ""])              # not before stable NG + alert time
        self.assertEqual(alerts[-1], "NG")
        self.assertTrue(any(e["event_type"] == "NG_ALERT" for s in snapshots for e in s.events))
        cleared = self.feed([mother()]+self.parts(), 6)
        self.assertEqual(cleared[-1].alert, "")

    def test_ambiguous_part_never_red(self):
        self.to_assembly()
        stray = shift([self.parts()[3]], -100)                       # midway between holes
        snapshot = self.feed([mother()]+self.parts()[:3]+stray, 20)[-1]
        self.assertEqual(snapshot.alert, "")
        self.assertNotEqual(snapshot.status, Status.NG)

    def test_auto_final_pass_then_next_recipe(self):
        self.to_assembly()
        snapshots = self.feed([mother()]+self.parts(), 30)
        final = snapshots[-1]
        self.assertEqual(final.phase, Phase.RESULT)
        self.assertEqual(final.result["result"], "PASS")
        self.assertEqual(final.result["decided_by"], "auto")
        events = [e for s in snapshots for e in s.events if e["event_type"] == "PRODUCT_RESULT"]
        self.assertEqual(len(events), 1)
        self.service.reset(load_recipe(ROOT/"config/recipes/recipe_2.json"))
        self.assertEqual(self.tick([mother()]).phase, Phase.CHECK_MATERIALS)
        self.assertEqual(self.service.product_seq, 1)

    def test_manual_complete_incomplete_is_final_ng_then_reassemble(self):
        self.to_assembly()
        self.feed([mother()]+self.parts()[:2], 6)                    # only H1 done
        self.assertTrue(self.service.complete())
        final = self.tick([mother()]+self.parts()[:2])
        self.assertEqual(final.phase, Phase.RESULT)
        self.assertEqual(final.result["result"], "NG")
        self.assertIn("MISSING_BOLT", [i["code"] for i in final.result["issues"]])
        self.assertTrue(self.service.reassemble())
        again = self.feed([mother()]+self.parts(), 30)[-1]
        self.assertEqual((again.phase, again.result["result"]), (Phase.RESULT, "PASS"))
        self.assertEqual(again.result["product_seq"], 2)


if __name__ == "__main__":
    unittest.main()
