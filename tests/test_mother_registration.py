import unittest
from dataclasses import replace
from math import pi, hypot
from pathlib import Path
from types import SimpleNamespace

from src.app.config import load_config
from src.contracts.detections import OBBDetection
from src.geometry.mother_registration import MotherRegistrar, MotherTracker, check_mother
from scripts.demo_data import mother

ROOT = Path(__file__).resolve().parents[1]


def measurement(alphas=(-0.4, -0.2, 0.0, 0.2, 0.4), visible=(True,)*5, beta=0.02):
    holes = tuple(SimpleNamespace(hole_id=i, alpha=a, beta=beta, visible=v)
                  for i, (a, v) in enumerate(zip(alphas, visible), 1))
    return SimpleNamespace(holes=holes, visible_count=sum(visible))


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        self.registrar = MotherRegistrar(self.config)
        self.mother = mother()                     # 1000 x 160 at (600, 700)
        self.ok = {"mother": measurement()}

    def run_frames(self, count, mothers=None, components=(), measurements=None, start=0, step=100):
        status = None
        for i in range(count):
            status = self.registrar.update(start+i*step, mothers or [self.mother], list(components),
                                           self.ok if measurements is None else measurements)
        return status

    def codes(self, status):
        return [i.code for i in status.issues]

    def test_locks_after_hands_off_period(self):
        status = self.run_frames(10)
        self.assertFalse(status.locked)
        self.assertIn("MOTHER_REGISTERING", self.codes(status))
        status = self.run_frames(2, start=1000)
        self.assertTrue(status.locked)
        geometry = status.lock.geometry(self.config)
        self.assertAlmostEqual(geometry["holes"][1][0], 200)
        self.assertAlmostEqual(geometry["holes"][5][0], 1000)
        self.assertAlmostEqual(geometry["holes"][3][1], 700+0.02*160)

    def test_measured_holes_replace_nominal_ratios(self):
        shifted = {"mother": measurement(alphas=(-0.38, -0.19, 0.01, 0.2, 0.39))}
        status = self.run_frames(12, measurements=shifted)
        self.assertTrue(status.locked)
        self.assertAlmostEqual(status.lock.geometry(self.config)["holes"][1][0], 600-380)

    def test_hidden_holes_side_face_or_small_part_rejected(self):
        side_face = {"mother": measurement(visible=(False, True, False, True, False))}
        status = self.run_frames(15, measurements=side_face)
        self.assertFalse(status.locked)
        self.assertIn("MOTHER_HOLES_NOT_VISIBLE", self.codes(status))

    def test_uneven_layout_rejected(self):
        bad = {"mother": measurement(alphas=(-0.4, -0.35, 0.0, 0.2, 0.4))}
        self.assertIn("MOTHER_HOLE_LAYOUT_MISMATCH", self.codes(self.run_frames(15, measurements=bad)))

    def test_short_part_shape_rejected(self):
        part = replace(self.mother, width=480)      # 3:1 like a 2-hole part
        issues = check_mother(part, measurement(), [], self.config)
        self.assertIn("MOTHER_SHAPE_MISMATCH", [i.code for i in issues])

    def test_component_on_mother_blocks(self):
        bolt = OBBDetection("b", "bolt_1", .9, (200, 700), 80, 80, 0)
        status = self.run_frames(15, components=[bolt])
        self.assertFalse(status.locked)
        self.assertIn("MOTHER_NOT_CLEAR", self.codes(status))
        far = replace(bolt, center_xy=(200, 100))
        self.assertTrue(self.run_frames(12, components=[far], start=2000).locked)

    def test_angle_limit(self):
        tilted = replace(self.mother, angle_rad=20*pi/180)
        self.assertIn("MOTHER_ANGLE_OUT_OF_RANGE", self.codes(self.run_frames(15, mothers=[tilted])))

    def test_movement_restarts_countdown(self):
        self.run_frames(8)
        moved = replace(self.mother, center_xy=(700, 700))
        status = self.run_frames(5, mothers=[moved], measurements={"mother": measurement()}, start=800)
        self.assertFalse(status.locked)
        self.assertLess(status.progress, 0.5)

    def test_frame_gap_restarts(self):
        self.run_frames(8)
        status = self.run_frames(3, start=2000)
        self.assertFalse(status.locked)

    def test_only_one_valid_mother_chosen(self):
        fake = replace(self.mother, detection_id="fake", center_xy=(600, 200))
        measurements = {"mother": measurement(), "fake": measurement(visible=(True, False, True, False, True))}
        status = self.run_frames(12, mothers=[self.mother, fake], measurements=measurements)
        self.assertTrue(status.locked)
        self.assertAlmostEqual(status.lock.center[1], 700)

    def test_missing_mother(self):
        status = self.registrar.update(0, [], [], {})
        self.assertIn("MOTHER_NOT_FOUND", self.codes(status))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        registrar = MotherRegistrar(self.config)
        for t in range(0, 1200, 100):
            status = registrar.update(t, [mother()], [], {"mother": measurement()})
        self.lock = status.lock
        self.tracker = MotherTracker(self.lock, self.config)

    def test_occlusion_keeps_lock(self):
        partial = replace(mother(), center_xy=(500, 700), width=700)   # hand hides one end
        lock, issues, events = self.tracker.update(1300, [partial])
        self.assertIs(lock, self.lock)
        self.assertEqual(issues, ())
        lock, issues, _ = self.tracker.update(1400, [])
        self.assertIs(lock, self.lock)
        self.assertEqual(issues, ())

    def test_long_loss_holds(self):
        self.tracker.update(1300, [])
        _, issues, _ = self.tracker.update(5000, [])
        self.assertEqual([i.code for i in issues], ["MOTHER_LOST"])

    def test_small_jitter_ignored(self):
        jitter = replace(mother(), center_xy=(610, 703))
        lock, issues, _ = self.tracker.update(1300, [jitter])
        self.assertIs(lock, self.lock)
        self.assertEqual(issues, ())

    def test_sustained_move_relocks_and_keeps_h1(self):
        moved = replace(mother(), center_xy=(750, 720), angle_rad=pi + 5*pi/180)   # same axis, flipped OBB angle
        for t in range(1300, 2300, 100):
            lock, issues, events = self.tracker.update(t, [moved])
            self.assertEqual([i.code for i in issues], ["MOTHER_MOVING"])
        lock, issues, events = self.tracker.update(2300, [moved])
        self.assertEqual(events[0]["event_type"], "MOTHER_RELOCKED")
        holes = lock.geometry(self.config)["holes"]
        self.assertLess(holes[1][0], holes[5][0])          # H1 still on the left
        self.assertAlmostEqual(hypot(holes[3][0]-750, holes[3][1]-720), 0.02*160, delta=1)


if __name__ == "__main__":
    unittest.main()
