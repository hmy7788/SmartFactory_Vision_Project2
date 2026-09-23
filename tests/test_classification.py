"""src/classification — torch 없이도 도는 부분(데이터 훑기·판정 규칙·지표)과, torch 가 있으면 끝까지 도는 smoke.

torch 가 없는 환경에서는 TorchSmokeTests 만 건너뛴다.
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from src.classification import decide, load_settings, scan, split, class_names
from src.classification.dataset import letterbox, load_image, summary
from src.classification.metrics import draw_confusion, markdown_table, report
from src.classification.synthetic import make_dataset

try:
    import torch  # noqa: F401
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False

ROOT = Path(__file__).resolve().parents[1]


class DatasetTests(unittest.TestCase):
    def test_scan_aabb_layout_reads_class_from_filename(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_dataset(d, per_class_train=2, per_class_test=1)
            # aabb 에는 부품 사진도 섞여 있다 — model_ 로 시작하지 않으면 무시해야 한다
            Image.new("RGB", (32, 32)).save(Path(root) / "images" / "train" / "bolt_1_001.png")
            Image.new("RGB", (32, 32)).save(Path(root) / "images" / "train" / "mother_part_001.png")
            s = scan(root)
            self.assertEqual(len(s), 9)
            self.assertEqual(class_names(s), ["model_a", "model_b", "model_c"])
            self.assertEqual(len(split(s, "train")), 6)
            self.assertEqual(len(split(s, "test")), 3)
            self.assertTrue(all(x.label == x.path.stem[:7] for x in s))
            self.assertIn("train 6", summary(s))

    def test_scan_class_folder_layout(self):
        with tempfile.TemporaryDirectory() as d:
            for sp, n in (("train", 2), ("test", 1)):
                for c in ("model_a", "model_b"):
                    (Path(d) / sp / c).mkdir(parents=True)
                    for i in range(n):
                        Image.new("RGB", (16, 9)).save(Path(d) / sp / c / f"img{i}.jpg")
            s = scan(d)
            self.assertEqual(len(s), 6)
            self.assertEqual(class_names(s), ["model_a", "model_b"])

    def test_letterbox_keeps_aspect_and_pads_black(self):
        img = Image.new("RGB", (1280, 720), (200, 200, 200))
        out = letterbox(img, 448)
        self.assertEqual(out.size, (448, 448))
        arr = np.array(out)
        self.assertEqual(tuple(arr[5, 224]), (0, 0, 0))        # 위 띠는 검정
        self.assertEqual(tuple(arr[224, 224]), (200, 200, 200))  # 가운데는 사진
        band = (448 - round(720 * 448 / 1280)) // 2
        self.assertEqual(tuple(arr[band + 2, 224]), (200, 200, 200))

    def test_load_image_accepts_opencv_bgr_frame(self):
        frame = np.zeros((10, 20, 3), dtype=np.uint8); frame[:, :, 0] = 255    # OpenCV BGR 로 파랑
        img = load_image(frame)
        self.assertEqual(img.size, (20, 10))
        self.assertEqual(img.getpixel((0, 0)), (0, 0, 255))                    # RGB 로 파랑

    def test_settings_map_every_recipe(self):
        st = load_settings()
        self.assertEqual(st["class_to_recipe"], {"model_a": "recipe_1", "model_b": "recipe_2", "model_c": "recipe_3"})
        for rid in st["class_to_recipe"].values():
            self.assertTrue((ROOT / "config" / "recipes" / f"{rid}.json").exists(), rid)
        self.assertGreater(st["unknown_threshold"], 0.34)   # 3 클래스 균등 확률(0.33)보다는 높아야 unknown 이 의미 있다


class DecideTests(unittest.TestCase):
    classes = ["model_a", "model_b", "model_c"]
    mapping = {"model_a": "recipe_1", "model_b": "recipe_2", "model_c": "recipe_3"}

    def test_confident_prediction_maps_to_recipe(self):
        r = decide([0.05, 0.9, 0.05], self.classes, 0.6, self.mapping)
        self.assertEqual((r.label, r.recipe_id, r.unknown), ("model_b", "recipe_2", False))
        self.assertAlmostEqual(r.confidence, 0.9)
        self.assertTrue(r.matches("recipe_2")); self.assertFalse(r.matches("recipe_1"))

    def test_low_confidence_is_unknown_and_never_matches(self):
        r = decide([0.4, 0.35, 0.25], self.classes, 0.6, self.mapping)
        self.assertEqual(r.label, "model_a"); self.assertTrue(r.unknown)
        self.assertFalse(r.matches("recipe_1"))

    def test_class_count_mismatch_is_loud(self):
        with self.assertRaises(ValueError):
            decide([0.5, 0.5], self.classes, 0.6, self.mapping)


class MetricsTests(unittest.TestCase):
    def test_report_and_table(self):
        rep = report([0, 0, 1, 1, 2, 2], [0, 0, 1, 2, 2, 2], ["a", "b", "c"])
        self.assertAlmostEqual(rep["accuracy"], 5 / 6, places=3)
        self.assertEqual(rep["confusion"], [[2, 0, 0], [0, 1, 1], [0, 0, 2]])
        self.assertEqual(rep["per_class"]["b"]["recall"], 0.5)
        self.assertEqual(rep["per_class"]["c"]["precision"], round(2 / 3, 4))
        md = markdown_table(rep)
        self.assertIn("| a | 1.00 | 1.00 | 1.00 | 2 |", md)
        with tempfile.TemporaryDirectory() as d:
            p = draw_confusion(rep, Path(d) / "cm.png")
            self.assertGreater(p.stat().st_size, 1000)


@unittest.skipUnless(HAVE_TORCH, "torch 가 없어 학습 smoke 는 건너뜀")
class TorchSmokeTests(unittest.TestCase):
    def test_train_predict_roundtrip_on_synthetic_data(self):
        from src.classification.train import main as train_main
        from src.classification.evaluate import main as eval_main
        from src.classification import Classifier
        with tempfile.TemporaryDirectory() as d:
            root = make_dataset(Path(d) / "data", per_class_train=6, per_class_test=2, size=(160, 90))
            out = Path(d) / "m.pt"; rep = Path(d) / "rep"
            code = train_main(["--data", str(root), "--out", str(out), "--report-dir", str(rep), "--img", "64",
                               "--epochs", "2", "--freeze-epochs", "1", "--batch", "6", "--no-pretrained", "--device", "cpu"])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            metrics = json.loads((rep / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["n"], 6)
            clf = Classifier.load(out)
            self.assertEqual(clf.classes, ["model_a", "model_b", "model_c"])
            r = clf.predict(next((root / "images" / "test").glob("model_a_*.png")))
            self.assertIn(r.label, clf.classes)
            self.assertAlmostEqual(sum(r.probs.values()), 1.0, places=4)
            self.assertEqual(r.recipe_id, {"model_a": "recipe_1", "model_b": "recipe_2", "model_c": "recipe_3"}[r.label])
            # OpenCV 프레임(BGR ndarray)도 같은 답
            frame = np.array(Image.open(next((root / "images" / "test").glob("model_b_*.png"))).convert("RGB"))[:, :, ::-1]
            self.assertIn(clf.predict(np.ascontiguousarray(frame)).label, clf.classes)
            code = eval_main(["--weights", str(out), "--data", str(root), "--report-dir", str(rep), "--gradcam", "3"])
            self.assertEqual(code, 0)
            self.assertTrue((rep / "eval_test.md").exists())
            self.assertGreaterEqual(len(list((rep / "gradcam").glob("*.jpg"))), 3)


if __name__ == "__main__":
    unittest.main()
