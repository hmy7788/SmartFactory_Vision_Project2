"""
rule_based_adapter.py

라이브 조립 검사에서 학습된 검출 모델(RT-DETR/YOLO) 없이, classical CV(색상 + 구멍 개수)만으로
프레임 안의 개별 부품(mother_part/part_3hole/part_2hole/bolt_1/bolt_2)을 찾아 InspectionService가
쓰는 DetectionFrame(OBBDetection)으로 바꾼다. src/rule_based/hole_count_check.py의 검은 배경
Otsu+RETR_CCOMP 방식(완성된 조립체 "하나"를 분석하도록 만들어짐)을 "여러 물체"로 확장한 것.

방법:
  1. find_all_blobs로 검은 배경 위 모든 전경 덩어리(+ 각 덩어리 안의 빈 구멍)를 찾는다.
  2. 덩어리 안 픽셀의 HSV 색상으로 볼트 후보를 가른다 (HSV_RANGES: 주황=bolt_2, 노랑=bolt_1).
     나무막대는 이 색 범위에 안 걸리므로(원목색/흰색) 색으로 볼트/막대가 자연히 갈린다.
  3. 나무막대 후보는 "빈 구멍 개수"로 1차 분류한다: 5=mother_part, 3=part_3hole, 2=part_2hole.
  4. 개수가 애매하면(아래 한계 참고), 같은 프레임에 mother_part(구멍 5개로 확정된
     막대)가 있을 때만 그 mother 길이 대비 이 막대의 길이 비율로 2차 판정한다
     (rtdetr_adapter.PART_NOMINAL_RATIO 재사용). 그래도 안 맞으면 이번 프레임에서
     검출하지 않는다(오분류보다 미검출이 낫다).
  5. 각 덩어리는 cv2.minAreaRect로 중심/장변/단변/각도를 직접 구한다 — 실제 컨투어가 있어서
     RT-DETR/YOLO(AABB)처럼 각도를 되짚어 복원할 필요가 없다(45도 부근 불안정 문제 자체가 없음).

⚠️ 한계 (알고 시작해야 함) — "빈 구멍 개수"에 기대는 이상 구조적으로 못 피한다:
  - 볼트가 구멍에 완전히 밀착해 꽂히면 그 구멍은 배경(검정)이 하나도 안 남아 "빈 구멍"으로도
    "분리된 볼트 덩어리"로도 안 잡혀 개수에서 통째로 빠진다 — 즉 볼트가 꽂힐수록 개수가
    줄어든다. 4번의 길이 비율 2차 판정이 mother가 화면에 있을 때는 이를 보완하지만,
    **줄어든 개수가 우연히 다른 클래스의 정상 개수와 같아지면(예: part_3hole에 볼트 1개
    꽂혀 빈 구멍 2개 → part_2hole의 정상 개수와 동일) "정확히 일치"로 먼저 처리돼 길이
    보정까지 가지도 못하고 오분류된다** — 이건 구조적 한계라 이 어댑터로는 못 고친다.
  - 부품끼리 서로 겹치거나 맞닿아 있으면(볼트 유무와 무관) 하나의 덩어리로 합쳐져 개별
    분리가 안 된다.
  - 프레임마다 독립적으로 다시 분석한다(추적 없음) — 한 번 확실히 분류됐던 부품이 다음
    프레임에 애매해지면(예: 손에 가려 구멍 일부만 보임) 그냥 그 프레임만 놓친다.
  - 그래서 부품이 서로 떨어져 있고 볼트가 안 꽂힌 재료 섹션(오피킹 검출)에서 가장 안정적이고,
    조립 섹션에서 이미 볼트가 꽂힌 부품을 계속 올바르게 인식하는 정확도는 RT-DETR/YOLO보다
    낮다 — 특히 위에서 말한 "우연히 다른 클래스와 개수가 같아지는" 경우.
"""

import math

import cv2
import numpy as np

from src.contracts.detections import DetectionFrame, OBBDetection
from src.rule_based.hole_count_check import HSV_RANGES, MIN_BOLT_AREA_RATIO, find_all_blobs

# 나무막대의 "총 구멍 개수"(빈 구멍 + 이미 꽂힌 볼트) -> 클래스.
HOLE_COUNT_TO_CLASS = {5: "mother_part", 3: "part_3hole", 2: "part_2hole"}
BOLT_COLOR_MIN_RATIO = 0.30   # 덩어리 픽셀 중 이 비율 이상이 볼트 색이어야 볼트로 인정
BAR_HOLE_CONFIDENCE = 0.85    # 총 구멍 개수가 정확히 맞아떨어졌을 때
BAR_RATIO_CONFIDENCE = 0.55   # mother 길이 대비 비율로 2차 판정했을 때 (덜 확실함)
# rtdetr_adapter.py와 같은 값 — 세로 정립 상태 사진(mother 530~540px)에서 실측:
# part_2hole ≈ 274x101, part_3hole ≈ 405x110 -> (길이, 폭)/mother_length 비율.
PART_NOMINAL_RATIO = {"part_2hole": (0.515, 0.19), "part_3hole": (0.755, 0.20)}
PART_RATIO_TOLERANCE = 0.12   # 위 비율에서 이 이상 벗어나면 후보에서 제외


def _wrap_half_pi(x):
    return (x + math.pi / 2) % math.pi - math.pi / 2


def _rect_shape(contour):
    """컨투어의 minAreaRect로 (center, 장변, 단변, 축각도[rad]) — AABB 역산이 필요 없어
    45도 부근에서도 항상 정확하다."""
    (cx, cy), (rw, rh), angle_deg = cv2.minAreaRect(contour)
    axis = _wrap_half_pi(math.radians(angle_deg if rw >= rh else angle_deg + 90.0))
    length, thickness = max(rw, rh), min(rw, rh)
    return (float(cx), float(cy)), float(length), float(thickness), axis


def _bolt_color(image, contour):
    """덩어리 내부 픽셀의 HSV로 어떤 볼트 색인지 판정. 못 맞추면 (None, 0.0)."""
    mask = np.zeros(image.shape[:2], np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, -1)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    pixels = hsv[mask > 0]
    if pixels.size == 0:
        return None, 0.0
    best_name, best_ratio = None, 0.0
    for name, ((h_lo, s_lo, v_lo), (h_hi, _, _)) in HSV_RANGES.items():
        in_range = ((pixels[:, 0] >= h_lo) & (pixels[:, 0] <= h_hi)
                    & (pixels[:, 1] >= s_lo) & (pixels[:, 2] >= v_lo))
        ratio = float(in_range.mean())
        if ratio > best_ratio:
            best_name, best_ratio = name, ratio
    return (best_name, best_ratio) if best_ratio >= BOLT_COLOR_MIN_RATIO else (None, best_ratio)


class RuleBasedAdapter:
    """모델 없이 classical CV만으로 프레임 -> DetectionFrame. 프레임 간 상태를 안 들고
    있다 (매 프레임 독립 분석) — RTDETRAdapter와 달리 reset()은 아무것도 하지 않는다."""

    def __init__(self):
        self._frame_id = 0

    def reset(self):
        pass

    def convert(self, frame, timestamp_ms):
        """frame: BGR 이미지(원본 좌표). 모델 result가 필요 없다."""
        area_ref = frame.shape[0] * frame.shape[1]
        blobs = find_all_blobs(frame, area_ref, min_area_ratio=MIN_BOLT_AREA_RATIO)

        bolts, bar_records = [], []
        for contour, empty_holes in blobs:
            name, ratio = _bolt_color(frame, contour)
            if name is not None:
                bolts.append((name, ratio, _rect_shape(contour)))
            else:
                bar_records.append((empty_holes, _rect_shape(contour)))

        # 1차: 빈 구멍 개수가 정확히 맞는 막대부터 분류해 mother 길이(있으면)를 확보한다.
        classified, mother_length = {}, None
        for i, (empty_holes, shape) in enumerate(bar_records):
            name = HOLE_COUNT_TO_CLASS.get(len(empty_holes))
            if name is not None:
                classified[i] = (name, BAR_HOLE_CONFIDENCE)
                if name == "mother_part":
                    mother_length = shape[1]

        # 2차: 개수가 애매한 막대는(볼트가 꽂혀 구멍이 줄었거나 등) mother 길이 대비 비율로.
        if mother_length is not None:
            for i, (_, shape) in enumerate(bar_records):
                if i in classified:
                    continue
                name = self._classify_by_length(shape[1], mother_length)
                if name is not None:
                    classified[i] = (name, BAR_RATIO_CONFIDENCE)

        frame_id = self._frame_id
        self._frame_id += 1
        detections = []
        idx = 0
        for name, ratio, (center, length, thickness, axis) in bolts:
            confidence = min(0.95, 0.5 + ratio)
            detections.append(OBBDetection(f"{frame_id}-{idx}", name, confidence, center, length, thickness, axis))
            idx += 1
        for i, (_, shape) in enumerate(bar_records):
            result = classified.get(i)
            if result is None:
                continue
            name, confidence = result
            center, length, thickness, axis = shape
            detections.append(OBBDetection(f"{frame_id}-{idx}", name, confidence, center, length, thickness, axis))
            idx += 1

        info = {"angle_source": "rule_based", "raw_blobs": len(blobs),
                "bars": len(bar_records), "bolts": len(bolts), "mother_angle_deg": None}
        mother = next((d for d in detections if d.class_name == "mother_part"), None)
        if mother is not None:
            info["mother_angle_deg"] = math.degrees(mother.angle_rad)
        return DetectionFrame(frame_id, timestamp_ms, tuple(detections)), info

    @staticmethod
    def _classify_by_length(length, mother_length):
        best_name, best_error = None, PART_RATIO_TOLERANCE
        for name, (ratio, _) in PART_NOMINAL_RATIO.items():
            error = abs(length / mother_length - ratio) / ratio
            if error < best_error:
                best_name, best_error = name, error
        return best_name
