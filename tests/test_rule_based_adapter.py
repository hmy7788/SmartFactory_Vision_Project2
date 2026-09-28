import math

import cv2
import numpy as np
import pytest

from src.vision.rule_based_adapter import BAR_HOLE_CONFIDENCE, RuleBasedAdapter

FRAME_W, FRAME_H = 640, 480
BAR_COLOR = (225, 225, 225)  # 검은 배경과 대비되는 밝은 색(원목/흰 부품 가정) — 볼트 색 범위 밖


def _hsv_color(hue, sat=200, val=220):
    """목표 hue(OpenCV 0~179 스케일)의 BGR 색을 정확히 계산 (HSV_RANGES 경계에 안 걸리게)."""
    pixel = np.uint8([[[hue, sat, val]]])
    return tuple(int(c) for c in cv2.cvtColor(pixel, cv2.COLOR_HSV2BGR)[0, 0])


BOLT_2_COLOR = _hsv_color(10)   # 주황 (HSV_RANGES: 0~18)
BOLT_1_COLOR = _hsv_color(25)   # 노랑 (HSV_RANGES: 18~35)


def _bar_polygon(center, length, thickness, angle_deg):
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([(center[0] + x * c - y * s, center[1] + x * s + y * c)
                     for x, y in ((-length / 2, -thickness / 2), (length / 2, -thickness / 2),
                                  (length / 2, thickness / 2), (-length / 2, thickness / 2))])


def _draw_bar(frame, center, length, thickness, angle_deg, n_holes, hole_radius=14):
    """막대를 그리고 장축을 따라 n_holes개 구멍(검은 원)을 균등 배치해 뚫는다."""
    polygon = _bar_polygon(center, length, thickness, angle_deg)
    cv2.fillPoly(frame, [polygon.astype(np.int32)], BAR_COLOR)
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    if n_holes == 1:
        alphas = [0.0]
    else:
        alphas = [-0.5 + i / (n_holes - 1) for i in range(n_holes)]
    for alpha in alphas:
        x = center[0] + alpha * (length - hole_radius * 3) * ux
        y = center[1] + alpha * (length - hole_radius * 3) * uy
        cv2.circle(frame, (int(x), int(y)), hole_radius, (0, 0, 0), -1)


def _draw_bolt(frame, center, color, radius=16):
    cv2.circle(frame, (int(center[0]), int(center[1])), radius, color, -1)


def _blank():
    return np.zeros((FRAME_H, FRAME_W, 3), np.uint8)


def _by_class(detections):
    return {d.class_name: d for d in detections}


def test_isolated_bars_classified_by_hole_count():
    frame = _blank()
    _draw_bar(frame, (100, 100), 140, 40, 0, 2)     # part_2hole
    _draw_bar(frame, (350, 100), 210, 44, 0, 3)     # part_3hole
    _draw_bar(frame, (250, 350), 300, 48, 0, 5)     # mother_part
    detection_frame, info = RuleBasedAdapter().convert(frame, 0.0)
    by_class = _by_class(detection_frame.detections)
    assert set(by_class) == {"part_2hole", "part_3hole", "mother_part"}
    assert info["bars"] == 3 and info["bolts"] == 0
    assert info["mother_angle_deg"] == pytest.approx(0.0, abs=2.0)


@pytest.mark.parametrize("degrees", [0, 30, 60, 90, -45])
def test_bar_orientation_recovered_at_any_angle(degrees):
    frame = _blank()
    _draw_bar(frame, (320, 240), 260, 46, degrees, 3)
    detection_frame, _ = RuleBasedAdapter().convert(frame, 0.0)
    assert len(detection_frame.detections) == 1
    part = detection_frame.detections[0]
    assert part.class_name == "part_3hole"
    error = abs(((math.degrees(part.angle_rad) - degrees + 90) % 180) - 90)
    assert error < 3
    assert part.width == pytest.approx(260, rel=0.08)
    assert part.height == pytest.approx(46, rel=0.15)


def test_bolt_colors_classified_by_hue():
    frame = _blank()
    _draw_bolt(frame, (150, 150), BOLT_2_COLOR)
    _draw_bolt(frame, (450, 150), BOLT_1_COLOR)
    detection_frame, info = RuleBasedAdapter().convert(frame, 0.0)
    by_class = _by_class(detection_frame.detections)
    assert set(by_class) == {"bolt_2", "bolt_1"}
    assert info["bolts"] == 2 and info["bars"] == 0
    for d in detection_frame.detections:
        assert 0.5 <= d.confidence <= 0.95


def test_bolt_fully_seated_in_hole_disappears_from_count():
    """볼트가 구멍에 완전히 밀착해 꽂히면(배경 틈이 안 남음) 나무 자체와 하나로 합쳐져서,
    그 구멍은 빈 구멍으로도 별도 볼트로도 안 잡히고 개수에서 통째로 빠진다(문서화된 한계).
    mother_part(구멍 5개)를 5구멍 중 1곳을 안 뚫어(=볼트가 이미 꽂힌 것처럼) 4개만 만들면,
    다른 mother 기준이 없는 한 애매한 개수로 미검출된다."""
    frame = _blank()
    _draw_bar(frame, (320, 240), 320, 50, 0, 4)  # 원래 5구멍이어야 할 막대가 4개만 보임
    detection_frame, info = RuleBasedAdapter().convert(frame, 0.0)
    assert detection_frame.detections == ()
    assert info["bolts"] == 0


def test_coincidental_hole_count_is_a_known_misclassification():
    """문서화된 한계: part_3hole에 볼트가 1개 꽂혀 빈 구멍이 2개로 줄면, 이 2개가 우연히
    part_2hole의 정상 개수와 같아서 mother가 있어도 길이 보정까지 못 가고 오분류된다."""
    frame = _blank()
    mother_length = 300
    _draw_bar(frame, (150, 100), mother_length, 48, 0, 5)
    # part_3hole 길이 비율(약 0.755)이지만 구멍은 2개만 보임(볼트 1개가 이미 꽂힌 것처럼).
    _draw_bar(frame, (450, 350), 0.755 * mother_length, 44, 0, 2)
    detection_frame, _ = RuleBasedAdapter().convert(frame, 0.0)
    by_class = _by_class(detection_frame.detections)
    assert by_class["part_2hole"].confidence == BAR_HOLE_CONFIDENCE  # "정확히 일치"로 먼저 처리됨
    assert "part_3hole" not in by_class


def test_ambiguous_hole_count_without_mother_reference_is_skipped():
    """5/3/2 어디에도 안 맞는 구멍 개수(4개)에, 비교 기준이 될 mother_part도 화면에 없으면
    오분류 대신 아예 검출하지 않는다."""
    frame = _blank()
    _draw_bar(frame, (320, 240), 300, 48, 0, 4)
    detection_frame, _ = RuleBasedAdapter().convert(frame, 0.0)
    assert detection_frame.detections == ()


def test_ambiguous_bar_falls_back_to_length_ratio_when_mother_present():
    """mother_part(구멍 5개, 확정)가 같이 있으면, 구멍 개수가 애매한 막대도 mother 대비
    길이 비율로 2차 판정한다."""
    frame = _blank()
    mother_length = 300
    _draw_bar(frame, (150, 100), mother_length, 48, 0, 5)
    # part_3hole 길이 비율(약 0.755)로 그리되, 구멍은 4개(애매한 개수)만 뚫는다.
    _draw_bar(frame, (450, 350), 0.755 * mother_length, 44, 0, 4)
    detection_frame, _ = RuleBasedAdapter().convert(frame, 0.0)
    by_class = _by_class(detection_frame.detections)
    assert "mother_part" in by_class
    assert "part_3hole" in by_class
    assert by_class["part_3hole"].confidence < by_class["mother_part"].confidence


def test_frame_id_increases_and_reset_is_noop():
    frame = _blank()
    adapter = RuleBasedAdapter()
    first, _ = adapter.convert(frame, 0.0)
    adapter.reset()
    second, _ = adapter.convert(frame, 100.0)
    assert second.frame_id == first.frame_id + 1
