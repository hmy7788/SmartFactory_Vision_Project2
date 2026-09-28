"""
rtdetr_adapter.py

RT-DETR(ultralytics)는 회전 없는 박스(AABB)만 내놓지만, InspectionService의 기하 계산
(mother_frame/roi_builder/association)은 OBB(중심, 폭, 높이, 각도)를 전제로 한다 —
detection_adapter.from_ultralytics는 result.obb가 없으면 에러를 낸다. 이 어댑터는 AABB에
빠져 있는 "각도"를 영상에서 복원해서 같은 DetectionFrame 계약(OBBDetection)으로 바꿔준다.

각도 복원 방식:
  - mother_part: 박스 안에서 빈 구멍(어두운 원)들의 중심을 찾아, 가장 많은 점이 한 직선에
    놓이는 조합(5구 축)의 각도를 쓴다 (src/rule_based/hole_count_check.py의 estimate_mother_angle
    재사용). 볼트로 막힌 구멍이 있어도 3~4개는 남아서 안정적이다. 프레임마다 흔들리지 않게
    지수이동평균으로 평활화하고, 일시적으로 못 구하면(손에 가림 등) 마지막 값을 잠깐 유지한다.
    끝내 못 구하면 0도로 가정하고 info에 "fallback"으로 표시한다.
  - 길이/두께: 각도를 알면 AABB(box_w, box_h)에서 막대 길이 L과 두께 t를 역산할 수 있다
    (box_w = L|cos|+t|sin|, box_h = L|sin|+t|cos|).
  - part_2hole/part_3hole: 박스 안 가장 큰 덩어리의 minAreaRect로 장축 각도를 구하되, 충분히
    길쭉하고 박스 길이와 비슷할 때만 믿는다. 아니면(mother와 붙어 덩어리가 합쳐진 경우 등)
    "mother와 수직"으로 가정해서, 각도를 잘못 재서 생기는 가짜 방향 오류를 만들지 않는다.
  - bolt_1/bolt_2: 중심점만 쓰이므로 각도 0으로 둔다.
  - RT-DETR은 NMS가 없어서 같은 부품이 거의 같은 자리에 두 번 검출되는 경우가 있다
    (model_b_029에서 실측) — 그러면 엔진이 MULTIPLE_MOTHERS 등으로 판정을 막으므로,
    같은 클래스끼리 IoU가 높은 박스는 confidence 높은 쪽만 남긴다.
"""

import math

import cv2
import numpy as np

from src.contracts.detections import CLASSES, DetectionFrame, OBBDetection
from src.rule_based.hole_count_check import _centroid, estimate_mother_angle, find_bar_and_holes

MIN_HOLE_INLIERS = 3          # mother 각도로 인정할 최소 구멍 개수 (같은 직선 위)
PART_MIN_ASPECT = 2.2         # 부품 각도를 믿기 위한 minAreaRect 최소 장단축비
PART_LENGTH_TOLERANCE = (0.7, 1.3)  # minAreaRect 장변 / 박스 장변 허용 범위
INVERSION_MIN_DET = 0.6       # AABB 역산이 안정적인 최소 |cos²-sin²| (약 ±28° 안쪽, 62° 바깥)
THICKNESS_SLICES = 20         # 두께 중앙값을 낼 때 장축을 나누는 조각 수
LENGTH_SANITY = (1.0, 1.05)   # 실측 길이는 [max(w,h), 대각선*1.05] 안이어야 믿는다
# 부품은 고정 크기의 강체라서 mother 길이 대비 (길이, 폭) 비율이 일정하다. 세로 정립 상태 사진
# (mother 530~540px)에서 실측: part_2hole ≈ 274x101, part_3hole ≈ 405x110 -> 아래 비율.
# 45도 근처처럼 AABB 역산도 minAreaRect도 못 믿을 때만 이 공칭 크기를 쓴다.
PART_NOMINAL_RATIO = {"part_2hole": (0.515, 0.19), "part_3hole": (0.755, 0.20)}


def _iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _wrap_half_pi(x):
    return (x + math.pi / 2) % math.pi - math.pi / 2


def bar_dims_from_aabb(box_w, box_h, axis_angle):
    """
    장축이 axis_angle(라디안, x축에서 아래쪽 방향)인 막대의 AABB가 (box_w, box_h)일 때
    (장축 길이 L, 두께 t)를 역산한다. 45도 근처는 식이 불안정해서 AABB를 그대로 쓴다.
    """
    c, s = abs(math.cos(axis_angle)), abs(math.sin(axis_angle))
    det = c * c - s * s
    if abs(det) > 0.3:
        length = (box_w * c - box_h * s) / det
        thickness = (box_h * c - box_w * s) / det
        if length > 0 and thickness > 0:
            return max(length, thickness), min(length, thickness)
    return max(box_w, box_h), min(box_w, box_h)


def inversion_is_stable(axis_angle):
    """AABB 역산식은 45도 근처(det->0)에서 무너진다 — 그 구간은 영상에서 직접 재야 한다."""
    return abs(math.cos(axis_angle) ** 2 - math.sin(axis_angle) ** 2) >= INVERSION_MIN_DET


def measure_bar_along_axis(frame, box, axis_angle, area_ref, pad=10):
    """
    mother 박스 안 가장 큰 덩어리를 장축(axis_angle) 방향으로 투영해서 (길이, 두께)를 잰다.
    길이는 장축 방향 전체 폭이라 세로로 붙은 부품이 있어도 영향이 없고, 두께는 장축을 따라 자른
    조각별 두께의 중앙값이라 세로 부품이 붙은 소수 구간에 흔들리지 않는다. 못 재면 None.
    """
    crop = _crop(frame, box, pad)
    if crop.size == 0:
        return None
    bar, _ = find_bar_and_holes(crop, area_ref)
    if bar is None:
        return None
    mask = np.zeros(crop.shape[:2], np.uint8)
    cv2.drawContours(mask, [bar], -1, 255, -1)
    ys, xs = np.nonzero(mask)
    c, s = math.cos(axis_angle), math.sin(axis_angle)
    along, across = xs * c + ys * s, -xs * s + ys * c
    length = float(along.max() - along.min())
    slices = np.digitize(along, np.linspace(along.min(), along.max(), THICKNESS_SLICES + 1))
    thickness = [float(across[slices == k].max() - across[slices == k].min())
                 for k in range(1, THICKNESS_SLICES + 1) if (slices == k).sum() > 20]
    return (length, float(np.median(thickness))) if thickness else None


def _crop(frame, box, pad):
    h, w = frame.shape[:2]
    x1, y1 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
    x2, y2 = min(w, int(box[2]) + pad), min(h, int(box[3]) + pad)
    return frame[y1:y2, x1:x2]


def estimate_mother_axis(frame, box, area_ref, pad=10):
    """mother 박스 안 빈 구멍들의 직선 피팅으로 5구 축 각도(라디안)를 구한다. 못 구하면 None."""
    crop = _crop(frame, box, pad)
    if crop.size == 0:
        return None
    _, holes = find_bar_and_holes(crop, area_ref)
    points = [c for c in (_centroid(h) for h in holes) if c is not None]
    angle, inliers = estimate_mother_angle(points)
    return angle if inliers >= MIN_HOLE_INLIERS else None


def estimate_part_axis(frame, box, pad=6):
    """
    부품 박스 안 가장 큰 덩어리의 (장축 각도(라디안), 장변, 단변). 길쭉하지 않거나 박스와
    안 맞으면 None. minAreaRect라서 어떤 각도에서도 길이/두께가 정확하다.
    """
    crop = _crop(frame, box, pad)
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    (_, _), (rw, rh), angle_deg = cv2.minAreaRect(max(contours, key=cv2.contourArea))
    long_side, short_side = max(rw, rh), min(rw, rh)
    if short_side <= 0 or long_side / short_side < PART_MIN_ASPECT:
        return None
    box_long = max(box[2] - box[0], box[3] - box[1])
    lo, hi = PART_LENGTH_TOLERANCE
    if not lo * box_long <= long_side <= hi * box_long:
        return None
    axis = math.radians(angle_deg if rw >= rh else angle_deg + 90.0)
    return _wrap_half_pi(axis), float(long_side), float(short_side)


class RTDETRAdapter:
    """RT-DETR Results -> DetectionFrame. 프레임 사이에 mother 각도 평활화 상태를 들고 있다."""

    def __init__(self, class_mapping=None, dedup_iou=0.5, angle_alpha=0.35, angle_hold_frames=20):
        self.class_mapping = class_mapping or {}
        self.dedup_iou = dedup_iou
        self.angle_alpha = angle_alpha
        self.angle_hold_frames = angle_hold_frames
        self._frame_id = 0
        self.reset()

    def reset(self):
        """새 제품/레시피 전환 시 평활화 상태만 초기화한다 (frame_id는 계속 증가시킴)."""
        self.mother_angle = None
        self._lost = 0

    def convert(self, result, frame, timestamp_ms):
        """
        result: ultralytics Results(boxes 사용), frame: 추론에 쓴 BGR 이미지(원본 좌표).
        Returns: (DetectionFrame, info dict)
        """
        boxes = result.boxes
        xyxy = boxes.xyxy.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)
        confidences = boxes.conf.cpu().numpy()

        items = []
        for box, class_id, confidence in zip(xyxy, classes, confidences):
            name = result.names[int(class_id)]
            name = self.class_mapping.get(name, name)
            if name in CLASSES:
                items.append({"box": tuple(float(v) for v in box), "name": name, "conf": float(confidence)})
        items.sort(key=lambda d: -d["conf"])
        kept = []
        for item in items:
            if not any(k["name"] == item["name"] and _iou(k["box"], item["box"]) > self.dedup_iou for k in kept):
                kept.append(item)

        area_ref = frame.shape[0] * frame.shape[1]
        mothers = [d for d in kept if d["name"] == "mother_part"]
        measured = estimate_mother_axis(frame, mothers[0]["box"], area_ref) if mothers else None
        if measured is not None:
            if self.mother_angle is None:
                self.mother_angle = measured
            else:
                self.mother_angle += self.angle_alpha * _wrap_half_pi(measured - self.mother_angle)
            self._lost = 0
            source = "measured"
        elif self.mother_angle is not None and self._lost < self.angle_hold_frames:
            self._lost += 1
            source = "held"
        else:
            self.mother_angle = None
            source = "fallback" if mothers else "no_mother"
        angle = self.mother_angle if self.mother_angle is not None else 0.0

        frame_id = self._frame_id
        self._frame_id += 1

        mother_dims = {}
        for item in kept:
            if item["name"] != "mother_part":
                continue
            x1, y1, x2, y2 = item["box"]
            box_w, box_h = x2 - x1, y2 - y1
            if box_w <= 0 or box_h <= 0:
                continue
            length, thickness = bar_dims_from_aabb(box_w, box_h, angle)
            if not inversion_is_stable(angle):
                measured_dims = measure_bar_along_axis(frame, item["box"], angle, area_ref)
                low, high = LENGTH_SANITY[0] * max(box_w, box_h), LENGTH_SANITY[1] * math.hypot(box_w, box_h)
                if measured_dims and low <= measured_dims[0] <= high:
                    length, thickness = measured_dims
            mother_dims[id(item)] = (length, thickness)
        mother_length = next(iter(mother_dims.values()), (None,))[0]

        detections = []
        for i, item in enumerate(kept):
            x1, y1, x2, y2 = item["box"]
            box_w, box_h = x2 - x1, y2 - y1
            if box_w <= 0 or box_h <= 0:
                continue
            name = item["name"]
            if name == "mother_part":
                length, thickness = mother_dims[id(item)]
                shape = (length, thickness, angle)
            elif name.startswith("part_"):
                part = estimate_part_axis(frame, item["box"])
                if part is not None:
                    axis, length, thickness = part
                else:
                    axis = _wrap_half_pi(angle + math.pi / 2)
                    if inversion_is_stable(axis) or mother_length is None:
                        length, thickness = bar_dims_from_aabb(box_w, box_h, axis)
                    else:
                        long_ratio, short_ratio = PART_NOMINAL_RATIO[name]
                        length, thickness = long_ratio * mother_length, short_ratio * mother_length
                shape = (length, thickness, axis)
            else:
                shape = (box_w, box_h, 0.0)
            detections.append(OBBDetection(f"{frame_id}-{i}", name, item["conf"],
                                           ((x1 + x2) / 2, (y1 + y2) / 2), *shape))

        info = {
            "mother_angle_deg": math.degrees(angle) if source != "no_mother" else None,
            "angle_source": source,
            "raw_boxes": len(items),
            "after_dedup": len(kept),
        }
        return DetectionFrame(frame_id, timestamp_ms, tuple(detections)), info
