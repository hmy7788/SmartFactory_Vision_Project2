"""src/vision/model_loader.py — 다른 모델을 UI 에 넣을 때의 판별·매핑 규칙. ultralytics 없이 가짜로 검증한다."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from src.vision.detection_adapter import from_ultralytics
from src.vision.model_loader import DEFAULT_MAPPING, check_names, load_mapping, load_model, resolve_mapping

CANON = {0: "bolt_2", 1: "bolt_1", 2: "mother_part", 3: "part_3hole", 4: "part_2hole"}


class _T:
    def __init__(self, rows): self.rows = rows
    def cpu(self): return self
    def tolist(self): return self.rows


class _Boxes:                       # detect(AABB) 결과 흉내 — RT-DETR 도 이 모양
    def __init__(self, xywh, cls, conf): self.xywh, self.cls, self.conf = _T(xywh), _T(cls), _T(conf)


class _Result:
    obb = None
    def __init__(self, names, boxes): self.names, self.boxes = names, boxes


class CheckNamesTests(unittest.TestCase):
    def setUp(self):
        self.mapping = load_mapping(DEFAULT_MAPPING)

    def test_core_names_need_no_mapping(self):
        ok, lines = check_names(CANON, self.mapping)
        self.assertTrue(ok); self.assertIn("코어 이름 그대로", lines[0])

    def test_korean_names_go_through_default_mapping(self):
        ok, _ = check_names({i: k for i, k in enumerate(self.mapping)}, self.mapping)
        self.assertTrue(ok)

    def test_unknown_name_stops_the_ui(self):
        ok, lines = check_names({**CANON, 5: "orange_bolt"}, self.mapping)
        self.assertFalse(ok); self.assertTrue(any("orange_bolt" in x for x in lines))

    def test_null_mapping_ignores_extra_class(self):
        ok, lines = check_names({**CANON, 5: "hand"}, {**self.mapping, "hand": None})
        self.assertTrue(ok); self.assertIn("무시", lines[0])

    def test_missing_part_is_only_a_warning(self):
        names = {k: v for k, v in CANON.items() if v != "part_2hole"}
        ok, lines = check_names(names, self.mapping)
        self.assertTrue(ok); self.assertTrue(any("part_2hole" in x for x in lines))


class MappingFileTests(unittest.TestCase):
    def test_sidecar_next_to_weights_wins_then_default(self):
        with tempfile.TemporaryDirectory() as d:
            w = Path(d) / "my_model.pt"; w.write_bytes(b"x")
            self.assertEqual(resolve_mapping(w), DEFAULT_MAPPING)
            side = Path(d) / "my_model.classes.json"; side.write_text(json.dumps({"a": "bolt_1"}), encoding="utf-8")
            self.assertEqual(resolve_mapping(w), side)
            other = Path(d) / "x.json"; other.write_text("{}", encoding="utf-8")
            self.assertEqual(resolve_mapping(w, other), other)          # --class-map 이 가장 우선

    def test_adapter_drops_null_mapped_detections(self):
        r = _Result({0: "bolt_1", 1: "hand"}, _Boxes([[10, 10, 4, 8], [50, 50, 20, 20]], [0, 1], [0.9, 0.8]))
        frame = from_ultralytics(r, 0, 1.0, {"hand": None})
        self.assertEqual([d.class_name for d in frame.detections], ["bolt_1"])
        self.assertEqual(frame.detections[0].angle_rad, 0.0)            # detect 결과는 각도 0


class LoadModelTests(unittest.TestCase):
    """ultralytics 대신 가짜 모듈: YOLO 로 열었는데 속이 RT-DETR 이면 RTDETR 로 다시 여는가."""

    def _fake_ultralytics(self, inner_cls_name, task="detect"):
        calls = []

        def make(cls_name):
            class Wrapper:
                def __init__(self, path):
                    calls.append((cls_name, path))
                    self.model = type(inner_cls_name, (), {})()
                    self.task, self.names = task, dict(CANON)
            Wrapper.__name__ = cls_name
            return Wrapper
        mod = types.ModuleType("ultralytics")
        mod.YOLO, mod.RTDETR = make("YOLO"), make("RTDETR")
        return mod, calls

    def _load(self, inner, model_type="auto", task="detect"):
        mod, calls = self._fake_ultralytics(inner, task)
        saved = sys.modules.get("ultralytics")
        sys.modules["ultralytics"] = mod
        try:
            with tempfile.TemporaryDirectory() as d:
                w = Path(d) / "m.pt"; w.write_bytes(b"0" * 1000)
                model, info = load_model(w, model_type)
        finally:
            if saved is None:
                sys.modules.pop("ultralytics", None)
            else:
                sys.modules["ultralytics"] = saved
        return model, info, [c for c, _ in calls]

    def test_yolo_obb_stays_yolo(self):
        model, info, calls = self._load("OBBModel", task="obb")
        self.assertEqual((info.kind, info.task, calls), ("yolo", "obb", ["YOLO"]))

    def test_rtdetr_checkpoint_is_reopened_as_rtdetr(self):
        model, info, calls = self._load("RTDETRDetectionModel")
        self.assertEqual((info.kind, type(model).__name__, calls), ("rtdetr", "RTDETR", ["YOLO", "RTDETR"]))
        self.assertIn("rtdetr", info.label)

    def test_explicit_type_skips_detection(self):
        _, info, calls = self._load("DetectionModel", model_type="rtdetr")
        self.assertEqual((info.kind, calls), ("rtdetr", ["RTDETR"]))

    def test_missing_file_is_clear(self):
        with self.assertRaises(FileNotFoundError):
            load_model("weights/없는파일.pt")


if __name__ == "__main__":
    unittest.main()
