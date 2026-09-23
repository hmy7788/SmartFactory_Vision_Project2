"""angle_refiner — 검은 배경에 그린 막대로 각도·두께·길이가 복원되는지 (사진 없이)."""
import math
import unittest

import cv2
import numpy as np

from src.contracts.detections import DetectionFrame, OBBDetection
from src.vision.angle_refiner import refine_angles, refine_detections


def draw_bar(img, center, length, thick, angle_deg, color=(150, 190, 205)):
    box = cv2.boxPoints((center, (length, thick), angle_deg)).astype(np.int32)
    cv2.fillPoly(img, [box], color)
    return box


def aabb(box, cls, i, conf=0.9):
    x0, y0 = box.min(0); x1, y1 = box.max(0)
    return OBBDetection(str(i), cls, conf, ((x0 + x1) / 2, (y0 + y1) / 2), float(x1 - x0), float(y1 - y0), 0.0)


class RefinerTests(unittest.TestCase):
    def scene(self, angle):
        """Mother 520×90 을 angle 로 놓고, H2 자리에 3구 파트를 수직으로 붙인다. 볼트는 H2 위."""
        img = np.full((720, 1280, 3), 20, np.uint8)
        W, T = 520.0, 90.0
        c = np.array([640.0, 420.0]); u = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))]); v = np.array([-u[1], u[0]])
        mbox = draw_bar(img, tuple(c), W, T, angle)
        hole = c + (-0.2 * W) * u                                   # H2
        pcenter = hole - 0.33 * W * v                               # 사양: 부품 중심은 구멍에서 0.33W 위
        pbox = draw_bar(img, tuple(pcenter), 0.8 * W, T, angle + 90)
        for k in (-0.4, -0.2, 0, 0.2, 0.4):                         # 구멍 5개 (배경색)
            h = c + k * W * u; cv2.circle(img, (int(h[0]), int(h[1])), 16, (20, 20, 20), -1)
        cv2.circle(img, (int(hole[0]), int(hole[1])), 28, (40, 160, 240), -1)   # 볼트
        bbox = np.array([[hole[0] - 30, hole[1] - 30], [hole[0] + 30, hole[1] + 30]])
        dets = (aabb(mbox, "mother_part", 0), aabb(pbox, "part_3hole", 1),
                OBBDetection("2", "bolt_2", 0.9, (float(hole[0]), float(hole[1])), 60.0, 60.0, 0.0))
        return img, dets, W, T

    def test_rotated_mother_and_part_get_their_angles_back(self):
        for angle in (0, 12, -25, 40):
            img, dets, W, T = self.scene(angle)
            out = refine_detections(img, dets)
            m = next(d for d in out if d.class_name == "mother_part")
            p = next(d for d in out if d.class_name == "part_3hole")
            self.assertAlmostEqual(math.degrees(m.angle_rad), angle, delta=2.0, msg=f"mother angle @{angle}")
            self.assertAlmostEqual(m.width, W, delta=0.06 * W, msg=f"mother length @{angle}")
            self.assertAlmostEqual(m.height, T, delta=0.2 * T, msg=f"mother thickness @{angle}")
            part_angle = (math.degrees(p.angle_rad) - (angle + 90) + 90) % 180 - 90
            self.assertAlmostEqual(part_angle, 0, delta=3.0, msg=f"part angle @{angle}")
            self.assertAlmostEqual(p.width, 0.8 * W, delta=0.1 * W, msg=f"part length @{angle}")

    def test_frame_without_single_mother_is_untouched(self):
        img = np.zeros((100, 100, 3), np.uint8)
        frame = DetectionFrame(1, 100, (OBBDetection("a", "bolt_1", 0.9, (10, 10), 5, 5, 0.0),))
        self.assertEqual(refine_angles(img, frame), frame)
        self.assertEqual(refine_angles(img, DetectionFrame(2, 200, (), input_valid=False)).input_valid, False)


if __name__ == "__main__":
    unittest.main()
