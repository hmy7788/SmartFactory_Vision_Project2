"""src/detection — torch/ultralytics 없이 도는 부분: 라벨 파싱·검사, 각도 규약, 데이터셋 폴더 만들기."""
import json
import math
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.detection import obb_labels as L
from src.detection.prepare_obb_dataset import build, collect, find_split_dir, guess_image_root, parse_args


def rect_points(cx, cy, w, h, deg):
    """중심·크기·각도(도) → 꼭짓점 4개 (정규화 좌표라고 치고 그대로 쓴다)."""
    t = math.radians(deg); c, s = math.cos(t), math.sin(t)
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


class LabelTests(unittest.TestCase):
    def test_parse_and_check(self):
        lb = L.parse_label_line("4 0.359821 0.331746 0.591071 0.331746 0.591071 0.469634 0.359821 0.469634", 1)
        self.assertEqual(lb.class_id, 4)
        self.assertEqual(len(lb.points), 4)
        self.assertEqual(L.check_label(lb), [])
        self.assertTrue(L.is_axis_aligned(lb.points))
        self.assertIn("AABB", str(self._err("1 0.5 0.5 0.2 0.1")))          # 5칸이면 OBB 가 아니라고 알려 준다
        self.assertIn("9칸", str(self._err("1 0.1 0.2 0.3")))
        self.assertIn("숫자", str(self._err("1 a b c d e f g h")))

    def _err(self, line):
        with self.assertRaises(ValueError) as cm:
            L.parse_label_line(line, 3)
        return cm.exception

    def test_check_flags_class_range_bounds_and_area(self):
        bad_class = L.ObbLabel(7, tuple(rect_points(0.5, 0.5, 0.2, 0.1, 0)))
        self.assertTrue(any("클래스" in p for p in L.check_label(bad_class)))
        outside = L.ObbLabel(2, tuple(rect_points(0.02, 0.5, 0.2, 0.1, 30)))
        self.assertTrue(any("밖" in p for p in L.check_label(outside)))
        self.assertEqual(L.check_label(outside, tol=0.2), [])                # 봐주는 폭 안이면 통과
        flat = L.ObbLabel(2, ((0.1, 0.1), (0.5, 0.1), (0.5, 0.1), (0.1, 0.1)))
        self.assertTrue(any("넓이" in p for p in L.check_label(flat)))
        self.assertTrue(all(0 <= v <= 1 for p in L.clip_label(outside).points for v in p))

    def test_rotated_label_is_not_axis_aligned(self):
        self.assertFalse(L.is_axis_aligned(rect_points(0.5, 0.5, 0.3, 0.1, 30)))
        self.assertTrue(L.is_axis_aligned(rect_points(0.5, 0.5, 0.3, 0.1, 0)))
        self.assertTrue(L.is_axis_aligned(rect_points(0.5, 0.5, 0.3, 0.1, 90)))

    def test_to_line_roundtrip(self):
        lb = L.ObbLabel(3, tuple(rect_points(0.4, 0.6, 0.3, 0.1, 20)))
        back = L.parse_label_line(lb.to_line())
        self.assertEqual(back.class_id, 3)
        for a, b in zip(lb.points, back.points):
            self.assertAlmostEqual(a[0], b[0], 5); self.assertAlmostEqual(a[1], b[1], 5)


class AngleTests(unittest.TestCase):
    def test_long_axis_matches_core_convention(self):
        # 긴 변이 세로(h > w)면 90° 를 더하고, 결과는 [-90, 90) 로 접는다 — src.geometry.mother_frame.major_axis 와 동일
        self.assertAlmostEqual(math.degrees(L.long_axis_angle(10, 40, 0.0)), -90.0, 5)
        self.assertAlmostEqual(math.degrees(L.long_axis_angle(10, 40, math.radians(10))), -80.0, 5)
        self.assertAlmostEqual(math.degrees(L.long_axis_angle(40, 10, math.radians(170))), -10.0, 5)
        self.assertAlmostEqual(math.degrees(L.long_axis_angle(40, 10, math.radians(-100))), 80.0, 5)

    def test_angle_error_is_symmetric_under_180(self):
        self.assertAlmostEqual(L.angle_error_deg(math.radians(10), math.radians(170)), 20.0, 5)
        self.assertAlmostEqual(L.angle_error_deg(math.radians(89), math.radians(-89)), 2.0, 5)
        self.assertAlmostEqual(L.angle_error_deg(math.radians(45), math.radians(-135)), 0.0, 5)

    def test_polygon_to_xywhr_recovers_long_axis(self):
        for deg in (0, 30, 75, 120, 160):
            pts = rect_points(320, 180, 200, 40, deg)
            cx, cy, w, h, ang = L.polygon_to_xywhr(pts)
            self.assertAlmostEqual(cx, 320, 2); self.assertAlmostEqual(cy, 180, 2)
            self.assertAlmostEqual(sorted((w, h))[1], 200, 1)
            self.assertLess(L.angle_error_deg(L.long_axis_angle(w, h, ang), math.radians(deg)), 0.6, msg=f"deg={deg}")

    def test_stem_group(self):
        cases = {"bolt_1_097": "bolt", "part_3hole_068": "part", "mother_part_028": "mother_part", "model_a_006": "model_a",
                 "2_hole_frame00005_000_jpg.rf.UhXNuu3PYyS108sPMd96": "2_hole", "b_frame00062_011_jpg.rf.x": "b",
                 "recipe1_process_frame00012_002_jpg.rf.abc": "recipe1_process"}
        for stem, group in cases.items():
            self.assertEqual(L.stem_group(stem), group, stem)


def make_source(root: Path, n_train=12, n_test=3, layout="flat"):
    """라벨 폴더 + 사진 폴더를 만든다. layout: flat(<root>/train), nested(<root>/labels/train, <root>/images/train)"""
    lab = root / "labels_src"; img = root / "images_src"
    for split, n in (("train", n_train), ("test", n_test)):
        ld = lab / split if layout == "flat" else lab / "labels" / split
        idir = img / split if layout == "flat" else img / "images" / split
        ld.mkdir(parents=True); idir.mkdir(parents=True)
        for i in range(n):
            group = ("bolt", "part", "model_a")[i % 3]
            stem = f"{group}_{i:03d}" if group != "model_a" else f"model_a_{i:03d}"
            cls = {"bolt": 1, "part": 3, "model_a": 2}[group]
            lines = [L.ObbLabel(cls, tuple(rect_points(0.5, 0.5, 0.3, 0.1, 30 if group == "part" else 0))).to_line()]
            if group == "model_a":
                lines.append(L.ObbLabel(0, tuple(rect_points(0.3, 0.3, 0.05, 0.05, 0))).to_line())
            (ld / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            Image.new("RGB", (64, 36), (10, 10, 10)).save(idir / f"{stem}.{'png' if group == 'model_a' else 'jpg'}")
    return lab, img


class PrepareTests(unittest.TestCase):
    def test_find_split_dir_handles_three_layouts(self):
        with tempfile.TemporaryDirectory() as d:
            for layout in ("flat", "nested"):
                lab, img = make_source(Path(d) / layout, layout=layout)
                self.assertIsNotNone(find_split_dir(lab, "train", (".txt",)), layout)
                self.assertIsNotNone(find_split_dir(img, "test", L.IMAGE_EXTS), layout)
            rf = Path(d) / "roboflow"; (rf / "train" / "labels").mkdir(parents=True); (rf / "train" / "labels" / "a.txt").write_text("")
            self.assertEqual(find_split_dir(rf, "train", (".txt",)), rf / "train" / "labels")
            self.assertIsNone(find_split_dir(rf, "test", (".txt",)))

    def test_build_writes_yaml_splits_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            lab, img = make_source(Path(d))
            out = Path(d) / "dataset"
            yaml = build(parse_args(["--labels", str(lab), "--images", str(img), "--out", str(out), "--val-frac", "0.25", "--seed", "1"]))
            text = yaml.read_text(encoding="utf-8")
            self.assertIn("val: images/val", text)
            self.assertIn("names:", text)
            self.assertIn("  0: bolt_2", text)
            self.assertIn("  4: part_2hole", text)
            splits = json.loads((out / "splits.json").read_text(encoding="utf-8"))
            self.assertEqual(len(splits["test"]), 3)
            self.assertEqual(len(splits["train"]) + len(splits["val"]), 12)
            self.assertEqual(len(splits["val"]), 3)                         # 묶음 3개 × 4장 × 25% = 1장씩
            self.assertTrue(all(any(s.startswith(g) for g in ("bolt", "part", "model_a")) for s in splits["val"]))
            for split, n in (("train", 9), ("val", 3), ("test", 3)):
                self.assertEqual(len(list((out / "images" / split).iterdir())), n, split)
                self.assertEqual(len(list((out / "labels" / split).iterdir())), n, split)
            rep = json.loads((out / "dataset_report.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["stats"]["test"]["images"], 3)
            self.assertIn("part_3hole", rep["stats"]["train"]["rotated_instances"])   # part 만 30° 로 기울였다
            self.assertNotIn("bolt_1", rep["stats"]["train"]["rotated_instances"])
            self.assertTrue((out / "dataset_report.md").exists())

    def test_val_frac_zero_uses_test_as_val(self):
        with tempfile.TemporaryDirectory() as d:
            lab, img = make_source(Path(d))
            out = Path(d) / "dataset"
            yaml = build(parse_args(["--labels", str(lab), "--images", str(img), "--out", str(out), "--val-frac", "0"]))
            self.assertIn("val: images/test", yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(list((out / "images" / "train").iterdir())), 12)
            self.assertIn("볼트_주황", build(parse_args(["--labels", str(lab), "--images", str(img), "--out", str(out),
                                                      "--val-frac", "0", "--korean-names", "--clean"])).read_text(encoding="utf-8"))

    def test_collect_reports_missing_images_and_bad_labels(self):
        with tempfile.TemporaryDirectory() as d:
            lab, img = make_source(Path(d), n_train=3, n_test=1)
            (lab / "train" / "orphan_001.txt").write_text("1 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2\n", encoding="utf-8")
            (lab / "train" / "bolt_000.txt").write_text("1 0.5 0.5 0.2 0.1\n", encoding="utf-8")          # AABB 5칸
            samples, missing, unreadable = collect(lab, img)
            self.assertEqual(missing["train"], ["orphan_001"])
            self.assertEqual(len(unreadable), 1)
            self.assertTrue(any("AABB" in v for v in unreadable.values()))
            self.assertEqual(len(samples), 3)

    def test_guess_image_root_finds_folder_next_to_labels(self):
        with tempfile.TemporaryDirectory() as d:
            lab, img = make_source(Path(d))
            stems = {s: [p.stem for p in (lab / s).glob("*.txt")] for s in ("train", "test")}
            best, scored = guess_image_root(lab, stems)
            self.assertEqual(best.resolve(), img.resolve())
            self.assertGreaterEqual(scored[0][1], 0.9)


if __name__ == "__main__":
    unittest.main()


class _T:
    """ultralytics 텐서 흉내: .cpu().tolist() / .numpy()"""
    def __init__(self, rows): self.rows = rows
    def cpu(self): return self
    def tolist(self): return self.rows
    def numpy(self):
        import numpy as np
        return np.asarray(self.rows, dtype=float)
    def __len__(self): return len(self.rows)


class _FakeYOLO:
    """정답 박스를 3° 돌려서 돌려주는 가짜 모델 — 각도 오차 계산이 맞는지 본다."""
    names = {i: n for i, n in enumerate(L.CLASS_NAMES)}
    task = "obb"
    labels_dir = None

    def __init__(self, weights): pass

    def predict(self, img, **kw):
        import cv2
        h, w = img.shape[:2]
        stem = _FakeYOLO.current_stem
        rows, cls, conf, corners = [], [], [], []
        for g in L.parse_label_file(_FakeYOLO.labels_dir / f"{stem}.txt"):
            cx, cy, bw, bh, ang = L.polygon_to_xywhr(L.points_to_pixels(g.points, w, h))
            rows.append([cx + 1, cy - 1, bw, bh, ang + math.radians(3)]); cls.append(float(g.class_id)); conf.append(0.9)
        obb = type("OBB", (), {})(); obb.xywhr = _T(rows); obb.cls = _T(cls); obb.conf = _T(conf)
        obb.__class__.__len__ = lambda self: len(rows)
        r = type("R", (), {})(); r.obb = obb if rows else None
        return [r]


class EvaluateStubTests(unittest.TestCase):
    def test_match_angles_and_report_with_fake_model(self):
        import sys, types
        import cv2
        from src.detection import evaluate_obb as E
        with tempfile.TemporaryDirectory() as d:
            lab, img = make_source(Path(d), n_train=6, n_test=6)
            out = Path(d) / "dataset"
            yaml = build(parse_args(["--labels", str(lab), "--images", str(img), "--out", str(out), "--val-frac", "0"]))
            _FakeYOLO.labels_dir = out / "labels" / "test"
            stub = types.ModuleType("ultralytics"); stub.YOLO = _FakeYOLO
            real_imread = cv2.imread

            def imread(path, *a):                       # 어떤 사진을 읽는지 가짜 모델에 알려 준다
                _FakeYOLO.current_stem = Path(path).stem
                return real_imread(path, *a)

            sys.modules["ultralytics"] = stub; cv2.imread = imread
            try:
                names = {i: n for i, n in enumerate(L.CLASS_NAMES)}
                ang = E.match_angles(Path("w.pt"), yaml, "test", 640, "cpu", 0.25, names)
            finally:
                del sys.modules["ultralytics"]; cv2.imread = real_imread
            self.assertEqual(ang["gt_bars"], 4)                   # test 6장: part 2장 + model_a(mother) 2장 → 막대 4개
            self.assertEqual(ang["matched"], 4)
            self.assertEqual(ang["overall"]["rotated"]["n"], 2)   # 회전 라벨은 part 만
            self.assertAlmostEqual(ang["overall"]["rotated"]["mean"], 3.0, delta=0.3)
            self.assertAlmostEqual(ang["overall"]["all"]["mean"], 3.0, delta=0.3)
            self.assertEqual(ang["per_class"]["part_3hole"]["rotated"]["n"], 2)
            self.assertEqual(ang["per_class"]["part_2hole"]["rotated"]["n"], 0)

            val = {"split": "test", "images": 6, "precision": 0.99, "recall": 0.98, "map50": 0.97, "map": 0.9,
                   "per_class": {n: {"precision": 0.9, "recall": 0.9, "map50": 0.95 - 0.01 * i, "map": 0.8} for i, n in enumerate(L.CLASS_NAMES)},
                   "val_speed_ms": {"inference": 12.3}, "names": names}
            speed = {"cpu": "fake cpu", "threads": 4, "image": "x.jpg", "cpu_640": {"median_ms": 80.0, "mean_ms": 82.0, "fps": 12.2},
                     "cpu_480": {"median_ms": 45.0, "mean_ms": 46.0, "fps": 21.7}}
            meta = {"model": "yolo11n-obb.pt", "epochs_run": 100, "best_epoch": 77, "device": "fake gpu", "minutes": 12.0, "cfg": {"imgsz": 640}}
            md = E.report_markdown(val, ang, speed, meta, Path("model/yolo_obb_parts.pt"))
            self.assertIn("| mAP50 | 0.986 | 0.978 | **0.970** |", md)
            self.assertIn("| part_2hole |", md)
            self.assertIn("가장 약한 클래스: **part_2hole**", md)
            self.assertIn("| cpu 640 | 80.0 | 82.0 | 12.2 |", md)
            self.assertIn("100 epoch (best 77)", md)
