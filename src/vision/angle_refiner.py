"""AABB 검출(회전 정보 없음)에 OpenCV 로 각도를 붙인다 — RT-DETR/YOLO-detect 가중치로 "삐뚤게 놓인" 경우까지 보려고.

    from src.vision.angle_refiner import refine_angles
    frame = refine_angles(frame_bgr, frame)      # DetectionFrame → DetectionFrame (각도·길이·두께가 채워진 OBB)

원리 — 배경이 어둡고 부품은 밝다는 촬영 조건을 그대로 쓴다.
  1. 프레임 전체를 Otsu 로 이진화 → 부품 마스크.
  2. Mother: 중심선 각도는 볼트가 2개 이상이면 볼트 중심들을 잇는 직선(볼트는 구멍 위에 앉으므로 정확),
     아니면 부품 AABB 를 지운 마스크에 직선을 맞춘다(fitLine, Huber). 두께는 중심선을 따라 거리변환(distance
     transform) 값의 중앙값 × 2. 길이는 중심선 띠 안의 픽셀을 축에 투영한 범위.
  3. Part: 크롭 마스크에서 Mother 띠를 지우고 열림(opening)으로 가장자리 조각을 없앤 뒤, 이 검출의 중심에 가장
     가까운 조각의 minAreaRect 로 각도. 길이·중심은 "먼 끝 → Mother 중심선 + 0.07W(사양의 부품 하단 여유)" 로 복원.
  4. Bolt: 그대로 (association 은 중심점만 본다).

한계 — 부품이 Mother 의 화면 아래쪽(+v)에 오는 뒤집힌 배치는 여기서 각도만으로 못 가른다. 코어의 mother_frame 이
각도를 [-90°, 90°) 로 접기 때문에 H1/H5 가 바뀌어 NG 가 난다. 그건 코어 규약(팀 결정) 문제라 여기서 손대지 않는다.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from src.contracts.detections import DetectionFrame, OBBDetection

PART_BOTTOM_OVERSHOOT = 0.07      # 사양(part_rois: length_ratio/2 - offset_ratio) — 부품 하단이 구멍 중심을 지나 내려오는 길이 / W


def object_mask(img_bgr) -> np.ndarray:
    """밝은 물체(나무·볼트) vs 어두운 배경. 프레임 전체 Otsu — 배경이 대부분이라 문턱이 안정적."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, m = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))      # 나뭇결·그림자 틈 메우기
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return m


def _crop(mask, d: OBBDetection, margin: float):
    cx, cy = d.center_xy
    w, h = d.width, d.height
    x0 = int(max(0, cx - w / 2 - margin * w)); x1 = int(min(mask.shape[1], cx + w / 2 + margin * w))
    y0 = int(max(0, cy - h / 2 - margin * h)); y1 = int(min(mask.shape[0], cy + h / 2 + margin * h))
    return mask[y0:y1, x0:x1], (x0, y0)


def _wrap(theta: float) -> float:
    return (theta + math.pi / 2) % math.pi - math.pi / 2           # [-90°, 90°)


def _polygon(center, width, height, angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([(center[0] + x * c - y * s, center[1] + x * s + y * c)
                     for x, y in ((-width / 2, -height / 2), (width / 2, -height / 2), (width / 2, height / 2), (-width / 2, height / 2))], np.int32)


def _inside_aabb(p, d: OBBDetection, margin=0.15) -> bool:
    return (abs(p[0] - d.center_xy[0]) <= d.width * (0.5 + margin)) and (abs(p[1] - d.center_xy[1]) <= d.height * (0.5 + margin))


def refine_mother(full_mask, d: OBBDetection, parts, bolts, part_polys=None):
    """→ (OBBDetection, (u, v)) 또는 (d, None). part_polys 가 있으면 AABB 대신 그 다각형(2차 추정)을 지운다."""
    m, (x0, y0) = _crop(full_mask, d, 0.12)
    if m.size == 0 or cv2.countNonZero(m) < 50:
        return d, None
    ys, xs = np.nonzero(m)
    pts_all = np.column_stack([xs, ys]).astype(np.float32) + [x0, y0]

    # ── 1. 중심선 각도 ──
    on_bar = [b for b in bolts if _inside_aabb(b.center_xy, d)]
    theta, point = None, None
    if len(on_bar) >= 2:
        bc = np.array([b.center_xy for b in on_bar], np.float32)
        vx, vy, px, py = cv2.fitLine(bc, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        theta, point = math.atan2(vy, vx), np.array([px, py])
    else:
        m_bar = m.copy()
        if part_polys:                                           # 2차: 1차에서 복원한 부품 다각형만 지운다 (AABB 보다 훨씬 작다)
            for poly in part_polys:
                cv2.fillPoly(m_bar, [poly - [x0, y0]], 0)
        else:
            for p in parts:                                      # 1차: 부품 AABB 를 지운다 (L 자가 직선 맞춤을 속이지 않게)
                px0 = int(p.center_xy[0] - p.width / 2 - x0); py0 = int(p.center_xy[1] - p.height / 2 - y0)
                px1 = int(p.center_xy[0] + p.width / 2 - x0); py1 = int(p.center_xy[1] + p.height / 2 - y0)
                cv2.rectangle(m_bar, (px0, py0), (px1, py1), 0, -1)
        if cv2.countNonZero(m_bar) < 0.12 * cv2.countNonZero(m):
            m_bar = m
        by, bx = np.nonzero(m_bar)
        pts_bar = np.column_stack([bx, by]).astype(np.float32) + [x0, y0]
        vx, vy, px, py = cv2.fitLine(pts_bar, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        theta, point = math.atan2(vy, vx), np.array([px, py])
        if len(on_bar) == 1:                                     # 볼트 하나면 중심선이 그 볼트를 지나게 (구멍은 중심선 위)
            point = np.array(on_bar[0].center_xy, np.float32)
    theta = _wrap(theta)
    u = np.array([math.cos(theta), math.sin(theta)]); v = np.array([-math.sin(theta), math.cos(theta)])

    # ── 2. 두께: 중심선을 따라 거리변환 값의 중앙값 × 2 ──
    filled = np.zeros_like(m)                                    # 구멍(배경으로 뚫린 원)을 메운 뒤에 재야 막대 두께가 나온다
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, cs, -1, 255, -1)
    dt = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
    rel = pts_all - point
    pu = rel @ u
    samples = []
    for t in np.linspace(pu.min(), pu.max(), 80):
        p = point + t * u
        xi, yi = int(round(p[0] - x0)), int(round(p[1] - y0))
        if 0 <= yi < dt.shape[0] and 0 <= xi < dt.shape[1] and dt[yi, xi] > 0:
            samples.append(dt[yi, xi])
    if len(samples) < 5:
        return d, None
    thickness = float(2 * np.median(samples))

    # ── 3. 길이·중심: 중심선 띠 안의 픽셀만 축에 투영 (부품은 띠 밖으로 뻗는다) ──
    pv = rel @ v
    band = np.abs(pv) <= thickness * 0.45
    if band.sum() < 10:
        band = np.ones_like(pu, bool)
    umin, umax = float(pu[band].min()), float(pu[band].max())
    center = point + ((umin + umax) / 2) * u + float(np.median(pv[band])) * v
    length = umax - umin
    if length <= thickness or thickness <= 0:
        return d, None
    return OBBDetection(d.detection_id, d.class_name, d.confidence, (float(center[0]), float(center[1])),
                        length, thickness, theta), (u, v)


def refine_part(full_mask, d: OBBDetection, mother: OBBDetection, uv):
    u, v = uv
    m, (x0, y0) = _crop(full_mask, d, 0.15)
    if m.size == 0:
        return d
    m2 = m.copy()
    cv2.fillPoly(m2, [_polygon(mother.center_xy, mother.width * 1.04, mother.height * 1.3, mother.angle_rad) - [x0, y0]], 0)
    k = max(3, int(mother.height * 0.15)) | 1                    # 막대 두께 기준 (AABB 는 회전하면 커진다)
    m2 = cv2.morphologyEx(m2, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    cs, _ = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cs = [c for c in cs if cv2.contourArea(c) >= 0.03 * d.width * d.height]
    if not cs:
        return d
    ctr = np.array([d.center_xy[0] - x0, d.center_xy[1] - y0])

    def dist(c):
        mm = cv2.moments(c)
        return math.hypot(mm["m10"] / mm["m00"] - ctr[0], mm["m01"] / mm["m00"] - ctr[1])

    cnt = min(cs, key=dist)                                      # 이 검출의 중심에 가장 가까운 조각이 이 부품
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(cnt)
    if rw < rh:
        rw, rh, ang = rh, rw, ang + 90
    cx, cy = cx + x0, cy + y0
    if rw < 1.4 * rh:                                            # 남은 조각이 네모에 가까우면 각도를 믿지 않는다 → Mother 에 수직으로
        theta = _wrap(mother.angle_rad + math.pi / 2)
        rh = min(rw, rh)
    else:
        theta = _wrap(math.radians(ang))
    axis = np.array([math.cos(theta), math.sin(theta)])
    if axis @ v < 0:
        axis = -axis                                             # Mother 쪽(+v)을 향하게
    denom = float(axis @ v)
    if abs(denom) < 0.3:                                         # Mother 와 나란한 조각 — 꽂힌 부품이 아니다
        return OBBDetection(d.detection_id, d.class_name, d.confidence, (float(cx), float(cy)), float(rw), float(rh), theta)
    far = np.array([cx, cy]) - axis * (rw / 2)                   # Mother 반대쪽 끝
    mc = np.array(mother.center_xy)
    t = float(((mc - far) @ v) / denom)                          # 먼 끝에서 Mother 중심선까지 축 방향 거리
    if t < rw * 0.5 or t > 1.2 * max(d.width, d.height) + mother.height:
        return OBBDetection(d.detection_id, d.class_name, d.confidence, (float(cx), float(cy)), float(rw), float(rh), theta)
    near = far + axis * (t + PART_BOTTOM_OVERSHOOT * mother.width)
    center = (far + near) / 2
    length = float(np.linalg.norm(near - far))
    return OBBDetection(d.detection_id, d.class_name, d.confidence, (float(center[0]), float(center[1])), length, float(rh), theta)


def refine_detections(img_bgr, detections, full_mask=None):
    """OBBDetection 튜플 → 각도가 채워진 튜플. Mother 가 정확히 하나가 아니면 그대로 돌려준다."""
    mothers = [d for d in detections if d.class_name == "mother_part"]
    if len(mothers) != 1:
        return tuple(detections)
    full = object_mask(img_bgr) if full_mask is None else full_mask
    parts = [d for d in detections if d.class_name.startswith("part_")]
    bolts = [d for d in detections if d.class_name.startswith("bolt_")]
    mother, uv = refine_mother(full, mothers[0], parts, bolts)
    if uv is None:
        return tuple(detections)
    refined_parts = [refine_part(full, d, mother, uv) for d in parts]
    if len([b for b in bolts if _inside_aabb(b.center_xy, mothers[0])]) < 2 and refined_parts:
        # 볼트로 각도를 못 잡은 경우: 1차로 복원한 부품 모양만 지우고 Mother 를 다시 맞춘다 (AABB 는 회전하면 막대를 너무 많이 가린다)
        polys = [_polygon(p.center_xy, p.width * 1.15, p.height * 1.4, p.angle_rad) for p in refined_parts]
        mother2, uv2 = refine_mother(full, mothers[0], parts, bolts, part_polys=polys)
        if uv2 is not None:
            mother, uv = mother2, uv2
            refined_parts = [refine_part(full, d, mother, uv) for d in parts]
    by_id = {p.detection_id: p for p in refined_parts}
    out = []
    for d in detections:
        if d.class_name == "mother_part":
            out.append(mother)
        elif d.class_name.startswith("part_"):
            out.append(by_id[d.detection_id])
        else:
            out.append(d)
    return tuple(out)


def refine_angles(img_bgr, frame: DetectionFrame) -> DetectionFrame:
    if not frame.input_valid or not frame.detections:
        return frame
    return DetectionFrame(frame.frame_id, frame.timestamp_ms, refine_detections(img_bgr, frame.detections), frame.input_valid)
