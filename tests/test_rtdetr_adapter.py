import math

import cv2
import numpy as np
import pytest

from src.vision.rtdetr_adapter import (RTDETRAdapter, _wrap_half_pi, bar_dims_from_aabb,
                                       estimate_part_axis)

FRAME_W, FRAME_H = 1280, 720


class _Tensor:
    def __init__(self, values):
        self.values = np.array(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class _Boxes:
    def __init__(self, entries):
        self.xyxy = _Tensor([e[1] for e in entries])
        self.cls = _Tensor([e[0] for e in entries])
        self.conf = _Tensor([e[2] for e in entries])


class _Result:
    names = {0: "bolt_2", 1: "bolt_1", 2: "mother_part", 3: "part_3hole", 4: "part_2hole"}

    def __init__(self, entries):
        self.boxes = _Boxes(entries)


def _bar_polygon(center, length, thickness, axis):
    c, s = math.cos(axis), math.sin(axis)
    return np.array([(center[0] + x * c - y * s, center[1] + x * s + y * c)
                     for x, y in ((-length / 2, -thickness / 2), (length / 2, -thickness / 2),
                                  (length / 2, thickness / 2), (-length / 2, thickness / 2))])


def _aabb(polygon):
    return (*polygon.min(axis=0), *polygon.max(axis=0))


def _mother_frame(axis, center=(640, 360), length=540, thickness=100):
    frame = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    polygon = _bar_polygon(center, length, thickness, axis)
    cv2.fillPoly(frame, [polygon.astype(np.int32)], (200, 220, 235))
    for alpha in (-0.4, -0.2, 0.0, 0.2, 0.4):
        x = center[0] + alpha * length * math.cos(axis)
        y = center[1] + alpha * length * math.sin(axis)
        cv2.circle(frame, (int(x), int(y)), 22, (0, 0, 0), -1)
    return frame, polygon


@pytest.mark.parametrize("degrees", [0, 8, -12, 90, 85, 100])
def test_bar_dims_round_trip(degrees):
    axis = math.radians(degrees)
    polygon = _bar_polygon((500, 300), 500, 100, axis)
    x1, y1, x2, y2 = _aabb(polygon)
    length, thickness = bar_dims_from_aabb(x2 - x1, y2 - y1, axis)
    assert length == pytest.approx(500, rel=0.02)
    assert thickness == pytest.approx(100, rel=0.05)


@pytest.mark.parametrize("degrees", [90, 100, 80, 75])
def test_part_axis_follows_rotation(degrees):
    axis = math.radians(degrees)
    frame = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    polygon = _bar_polygon((640, 360), 300, 80, axis)
    cv2.fillPoly(frame, [polygon.astype(np.int32)], (200, 220, 235))
    estimate = estimate_part_axis(frame, _aabb(polygon))
    assert estimate is not None
    estimated_axis, long_side, short_side = estimate
    error = abs(_wrap_half_pi(estimated_axis - axis))
    assert math.degrees(error) < 3
    assert long_side == pytest.approx(300, rel=0.05) and short_side == pytest.approx(80, rel=0.1)


def test_mother_angle_recovered_from_holes():
    axis = math.radians(8)
    frame, polygon = _mother_frame(axis)
    adapter = RTDETRAdapter()
    detection_frame, info = adapter.convert(_Result([(2, _aabb(polygon), 0.95)]), frame, 100.0)
    assert info["angle_source"] == "measured"
    assert math.degrees(abs(_wrap_half_pi(math.radians(info["mother_angle_deg"]) - axis))) < 2
    mother = detection_frame.detections[0]
    assert mother.class_name == "mother_part"
    assert mother.width == pytest.approx(540, rel=0.08)
    assert mother.height == pytest.approx(100, rel=0.2)


@pytest.mark.parametrize("degrees", [-50, -38, 35, 45, 55])
def test_mother_size_is_correct_near_45_degrees(degrees):
    """AABB 역산이 무너지는 구간(약 28~62°)에서도 영상 실측으로 길이/두께가 맞아야 한다."""
    axis = math.radians(degrees)
    frame, polygon = _mother_frame(axis)
    detection_frame, info = RTDETRAdapter().convert(_Result([(2, _aabb(polygon), 0.95)]), frame, 0.0)
    assert info["angle_source"] == "measured"
    mother = detection_frame.detections[0]
    assert mother.width == pytest.approx(540, rel=0.06)
    assert mother.height == pytest.approx(100, rel=0.2)


def test_duplicate_boxes_of_same_class_are_dropped():
    frame, polygon = _mother_frame(0.0)
    box = _aabb(polygon)
    shifted = (box[0] + 2, box[1] + 1, box[2] + 2, box[3] + 1)
    detection_frame, info = RTDETRAdapter().convert(
        _Result([(2, box, 0.92), (2, shifted, 0.63)]), frame, 0.0)
    assert info["raw_boxes"] == 2 and info["after_dedup"] == 1
    assert [d.class_name for d in detection_frame.detections] == ["mother_part"]
    assert detection_frame.detections[0].confidence == pytest.approx(0.92)


def test_all_classes_convert_and_frame_ids_increase():
    frame, polygon = _mother_frame(0.0)
    entries = [(2, _aabb(polygon), 0.9), (1, (400, 330, 440, 370), 0.8),
               (0, (560, 330, 600, 370), 0.85), (3, (600, 100, 690, 330), 0.9)]
    adapter = RTDETRAdapter()
    first, _ = adapter.convert(_Result(entries), frame, 0.0)
    second, _ = adapter.convert(_Result(entries), frame, 100.0)
    assert {d.class_name for d in first.detections} == {"mother_part", "bolt_1", "bolt_2", "part_3hole"}
    assert second.frame_id == first.frame_id + 1


def test_angle_is_held_briefly_then_falls_back():
    axis = math.radians(5)
    frame, polygon = _mother_frame(axis)
    blank = np.zeros_like(frame)
    adapter = RTDETRAdapter(angle_hold_frames=2)
    result = _Result([(2, _aabb(polygon), 0.9)])
    adapter.convert(result, frame, 0.0)
    sources = [adapter.convert(result, blank, 100.0 * (i + 1))[1]["angle_source"] for i in range(4)]
    assert sources == ["held", "held", "fallback", "fallback"]
