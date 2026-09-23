"""CHECK_MATERIALS -> REGISTER_MOTHER -> ASSEMBLING with a locked Mother."""
import unittest
from dataclasses import replace
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.contracts.inspection import Phase, Status
from src.process.recipe import load_recipe
from scripts.demo_data import mother, components

ROOT = Path(__file__).resolve().parents[1]

try:
    import cv2
    import numpy as np
except ImportError:          # optional: only the image test needs OpenCV
    cv2 = None


class RegisteredFlowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        self.assertTrue(self.config["registration"]["enabled"])
        self.recipe = load_recipe(ROOT/"config/recipes/recipe_1.json")
        self.service = InspectionService(self.config, self.recipe)
        self.time, self.frame_id = -100, -1

    def tick(self, detections, delta=100, image=None):
        self.time += delta
        self.frame_id += 1
        return self.service.update(DetectionFrame(self.frame_id, self.time, tuple(detections)), image)

    def feed(self, detections, count, image=None):
        return [self.tick(detections, image=image) for _ in range(count)][-1]

    def parts(self):
        return components(self.recipe, self.config)

    def inventory(self):
        return [mother()]+[replace(d, center_xy=(100+i*200, 100)) for i, d in enumerate(self.parts())]

    def to_assembly(self):
        ready = self.feed(self.inventory(), 11)
        self.assertEqual(ready.phase, Phase.REGISTER_MOTHER)
        self.assertEqual(ready.events[-1]["event_type"], "MATERIALS_READY")
        locked = self.feed([mother()], 11)
        self.assertEqual(locked.phase, Phase.ASSEMBLING)
        self.assertEqual(locked.events[-1]["event_type"], "ASSEMBLY_STARTED")
        return locked

    def codes(self, snapshot):
        return [i.code for i in snapshot.candidate.issues]

    def test_full_flow_passes(self):
        locked = self.to_assembly()
        self.assertTrue(locked.registration["locked"])
        self.assertAlmostEqual(locked.registration["holes"][1][0], 200)
        self.assertEqual(self.feed([mother()]+self.parts(), 5).status, Status.PASS)

    def test_registration_waits_until_hands_off(self):
        self.feed(self.inventory(), 11)
        snapshot = self.feed([mother()], 5)
        self.assertEqual(snapshot.phase, Phase.REGISTER_MOTHER)
        self.assertIn("MOTHER_REGISTERING", self.codes(snapshot))
        self.assertGreater(snapshot.registration["progress"], 0.3)

    def test_parts_on_mother_block_registration(self):
        self.feed(self.inventory(), 11)
        snapshot = self.feed([mother()]+self.parts(), 20)
        self.assertEqual(snapshot.phase, Phase.REGISTER_MOTHER)
        self.assertIn("MOTHER_NOT_CLEAR", self.codes(snapshot))

    def test_hand_hiding_mother_and_bolt_keeps_pass(self):
        self.to_assembly()
        self.feed([mother()]+self.parts(), 5)
        hidden = [d for d in self.parts() if d.detection_id != "b1"]          # H1 bolt under the hand
        for _ in range(10):                                                    # 1 s, no Mother detection
            snapshot = self.tick(hidden)
            self.assertEqual(snapshot.status, Status.PASS)
            self.assertEqual(snapshot.candidate.status, Status.PASS)
        self.assertIn(1, snapshot.occluded)

    def test_removed_correct_bolt_reported_after_hold(self):
        self.to_assembly()
        self.feed([mother()]+self.parts(), 5)
        without = [mother()]+[d for d in self.parts() if d.detection_id != "b1"]
        self.assertEqual(self.feed(without, 10).status, Status.PASS)          # still assumed hidden
        snapshot = self.feed(without, 10)                                      # > 1.5 s + 0.4 s
        self.assertEqual(snapshot.status, Status.IN_PROGRESS)
        self.assertIn("MISSING_BOLT", self.codes(snapshot))

    def test_wrong_bolt_ng_clears_immediately_when_removed(self):
        self.to_assembly()
        wrong = [mother()]+[replace(d, class_name="bolt_2") if d.detection_id == "b1" else d for d in self.parts()]
        snapshot = self.feed(wrong, 5)
        self.assertEqual(snapshot.status, Status.NG)
        self.assertIn("WRONG_BOLT", self.codes(snapshot))
        removed = [mother()]+[d for d in self.parts() if d.detection_id != "b1"]
        self.assertEqual(self.feed(removed, 5).status, Status.IN_PROGRESS)

    def test_extra_bolt_in_h2_is_ng(self):
        self.to_assembly()
        x = 600 + self.config["hole_alphas"][1]*1000
        extra = OBBDetection("x2", "bolt_1", .99, (x, 700), 80, 80, 0)
        snapshot = self.feed([mother()]+self.parts()+[extra], 5)
        self.assertEqual(snapshot.status, Status.NG)
        self.assertIn(("UNEXPECTED_COMPONENT", 2), [(i.code, i.hole_id) for i in snapshot.candidate.issues])

    def test_misaligned_part_does_not_freeze_other_holes(self):
        self.to_assembly()
        parts = self.parts()
        # H4 part slid sideways between two holes: fits no Hole -> ambiguous.
        stray = replace(parts[3], detection_id="p4", center_xy=(parts[3].center_xy[0]-100, parts[3].center_xy[1]))
        ds = [mother(), parts[0], parts[1], parts[2], stray]
        first = self.feed(ds, 3)
        self.assertNotEqual(first.candidate.status, Status.HOLD)            # other holes still judged
        self.assertIn("MISSING_PART", self.codes(first))
        self.assertNotIn("AMBIGUOUS_ASSOCIATION", self.codes(first))       # not reported yet
        later = self.feed(ds, 10)
        self.assertEqual(later.status, Status.IN_PROGRESS)
        self.assertIn("AMBIGUOUS_ASSOCIATION", self.codes(later))
        self.assertIn("p4", later.geometry["ambiguous_detections"])
        self.assertEqual(self.feed([mother()]+parts, 5).status, Status.PASS)

    def test_mother_lost_long_holds(self):
        self.to_assembly()
        self.feed([mother()]+self.parts(), 5)
        snapshot = self.feed([], 40)
        self.assertEqual(snapshot.status, Status.HOLD)
        self.assertIn("MOTHER_LOST", self.codes(snapshot))

    def test_mother_moved_relocks(self):
        self.to_assembly()
        shift = 150
        moved = [replace(d, center_xy=(d.center_xy[0]+shift, d.center_xy[1])) for d in [mother()]+self.parts()]
        first = self.tick(moved)
        self.assertIn("MOTHER_MOVING", self.codes(first))
        snapshots = [self.tick(moved) for _ in range(16)]
        self.assertTrue(any(e.get("event_type") == "MOTHER_RELOCKED" for s in snapshots for e in s.events))
        self.assertEqual(snapshots[-1].status, Status.PASS)
        self.assertAlmostEqual(snapshots[-1].registration["holes"][1][0], 200+shift)

    def test_reregister(self):
        self.to_assembly()
        self.service.reregister()
        snapshot = self.tick([mother()])
        self.assertEqual(snapshot.phase, Phase.REGISTER_MOTHER)

    @unittest.skipIf(cv2 is None, "OpenCV not installed")
    def test_image_measured_holes_are_used(self):
        # Synthetic top view: beige Mother with five dark holes, H1 slightly off nominal.
        image = np.full((900, 1280, 3), (60, 40, 30), np.uint8)
        cv2.rectangle(image, (100, 620), (1100, 780), (170, 200, 210), -1)
        xs = [215, 400, 600, 800, 1000]
        for x in xs:
            cv2.circle(image, (x, 700), 28, (15, 15, 15), -1)
        self.feed(self.inventory(), 11)
        locked = self.feed([mother()], 11, image=image)
        self.assertTrue(locked.registration["measured"])
        self.assertAlmostEqual(locked.registration["holes"][1][0], 215, delta=3)


if __name__ == "__main__":
    unittest.main()
