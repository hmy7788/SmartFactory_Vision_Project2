"""
hole_count_check.py

CLAUDE.md 3-2 룰베이스(필수): 완성된 조립체 사진에서 구멍 개수를 세어
Model A/B/C 중 어디에 해당하는지 분류한다. "블록 개수 세기"가 아니라
"구멍 개수 세기"로 판정한다 (CLAUDE.md 3-2 방침).

설계 변천사:
  1차: 막대별 vertical_holes/horizontal_holes(CLAUDE.md 원안) — 조립 상태에서는 막대들이
       맞닿아 컨투어가 하나로 합쳐져서 막대별 분리가 안 됨 + Model A/B는 세로 막대가 2개라
       스키마 자체가 안 맞음.
  2차: (총 구멍 개수, bolt_1 개수, bolt_2 개수) — 구멍 개수만으로 Model B/C가 둘 다 7개라
       안 겹쳐서 볼트 색상(HSV)을 더했는데, 조명 편차에 약해 실측 100장 정답률이 61%에 그침.
  3차: 볼트 색상 대신 "구멍의 상대적 위치"를 이용 — 접합용 볼트는 항상 세로 막대의
       **맨 아래 구멍**에 꽂히고, 나머지 구멍은 전부 비어있다. 그래서 세로 막대마다
       "접합점 위쪽 빈 구멍 개수"만 세면 색상 없이도 완전히 구분된다:
         part_2hole(구멍 2개) 세로 막대 -> 위쪽 빈 구멍 1개
         part_3hole(구멍 3개) 세로 막대 -> 위쪽 빈 구멍 2개
       MODEL_A = [2, 1]  # part_3hole + part_2hole
       MODEL_B = [1, 1]  # part_2hole x2
       MODEL_C = [2]     # part_3hole
       위쪽 구멍은 볼트가 꽂힐 일이 없는 자리라(접합점은 항상 맨 아래), 색상 인식이 아예
       필요 없다 — HSV 의존성 완전히 제거.
  4차: 3차는 "mother_part가 화면에서 항상 수평"이라고 가정했는데, ICONIC 촬영
       스펙 자체가 0/45/90/135도 다양한 각도를 포함해서 조립체도 비스듬히 놓인 사진이
       많다 — 이 경우 "가로로 가장 넓은 밴드" 찾기가 통째로 깨진다. 그래서 분석 전에
       mother_part의 회전각을 구해서 수평으로 되돌리는 단계를 추가했다.
       각도는 검출된 "빈 구멍" 중심점들로 구한다 — mother_part는 구멍이 5개(일부가
       볼트로 막혀도 최소 3~4개는 빈 채로 남음) 일직선으로 늘어서 있고, 세로 막대는
       구멍이 최대 2개뿐이라 점 개수로 구분된다. 모든 점 쌍에 대해 그 직선에 몇 개 점이
       가까이 있는지(RANSAC과 같은 아이디어) 세서, 가장 많은 점을 지나는 직선을
       mother_part의 축으로 판정하고 그 각도만큼 이미지를 회전시킨다.
       또한 접합점(joint) 위치에서만 국소적으로 색을 샘플링해 볼트 색상(bolt_1/bolt_2)도
       검증한다 — 구조가 맞아도 엉뚱한 색 볼트를 쓴 경우를 잡기 위함.
  5차(현재): 구조+색상이 맞아도 "어느 mother_hole에 붙었는지"(정확한 위치)까지는
       못 잡는 문제가 있었다 — 실사용 테스트에서 발견됨(같은 구성이지만 다른 구멍에
       꽂아도 통과했음). `config/recipes/recipe_*.json`(팀 합의로 0-based, 왼쪽부터
       0,1,2,3,4)를 기준으로 각 세로 막대의 접합점이 정확히 몇 번 구멍인지까지 검증한다.
       mother_part의 5개 구멍 위치(빈 구멍 + 접합점)를 x좌표로 정렬해 0~4번을 매기는데,
       회전 보정은 각도만 알려줄 뿐 어느 쪽 끝이 "왼쪽 0번"인지(180도 방향)는 못 정해주므로
       감지된 순서 그대로 읽는 경우와 반대로(mirror) 읽는 경우 둘 다 시도해서 하나라도
       맞으면 통과시킨다.

방법:
  1. cv2.findContours(RETR_CCOMP)로 나무 구조물의 (가장 큰) 외곽 컨투어 하나와 "빈" 구멍들을 찾는다.
  2. 빈 구멍 중심점들로 mother_part의 회전각을 추정하고(직선 피팅), 그만큼 이미지를
     되돌려 mother_part가 수평이 되게 만든 뒤 1번을 다시 수행한다.
  3. 외곽 컨투어를 채운 마스크에서 가로로 가장 넓은 밴드(=mother_part 몸통)를 찾는다.
  4. 그 밴드보다 위쪽 영역만 떼어내 연결요소(connectedComponents)를 구하면, 각 덩어리가
     세로 막대 하나씩에 대응한다.
  5. 전체 컨투어의 "빈 구멍" 자식 컨투어 중 밴드보다 위(=세로 막대 쪽)에 있는 것만, 어느
     연결요소에 속하는지로 묶어서 막대별 개수를 센다 — 이게 각 세로 막대의 "위쪽 구멍 개수".
  6. 이 개수들의 다중집합(정렬된 리스트)을 모델 시그니처와 비교해 분류.

사용법:
    python src/rule_based/hole_count_check.py --input data/aabb/images/test/model_a_006.png
    python src/rule_based/hole_count_check.py --input <경로> --debug-output <경로>
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "detection"))
from auto_label_iconic import imread_unicode, imwrite_unicode  # noqa: E402

# 세로 막대별 "접합점 위쪽 빈 구멍 개수"의 다중집합(내림차순) — 색상 무관, 순수 형태 기반
MODEL_SIGNATURES = {
    "MODEL_A": [2, 1],  # part_3hole(위쪽 2개) + part_2hole(위쪽 1개)
    "MODEL_B": [1, 1],  # part_2hole x2
    "MODEL_C": [2],     # part_3hole
}

# ⚠️ config/recipes/recipe_*.json(0-based으로 팀과 합의: 왼쪽 시작 0,1,2,3,4)에서 가져온
# "몇 번 mother_hole에 어떤 부품+볼트가 붙어야 하는지". 구조(구멍 위치 개수)만으로는
# 형태가 같은 한 "볼트 색상이 틀려도"/"엉뚱한 구멍에 꽂아도" 못 잡는다 — 예를 들어
# part_2hole 자리에 bolt_2(주황)를 꽂거나 다른 구멍에 꽂아도 구멍 개수만으로는 통과해버림.
# 그래서 색상+위치를 여기서 한 번에 검증한다.
# part_2hole=bolt_1(노랑), part_3hole=bolt_2(주황)로 모델 상관없이 고정 (2026-09-23 팀 확인
# — 한때 Model C의 part_3hole이 bolt_1이라는 혼선이 있었으나 Model B/C를 착각한 것으로
# 정정됨, recipe_3.json 원래 값(bolt_2)이 맞음). 그래도 "부품→색"을 전역 상수로 빼지 않고
# 모델별 배치마다 명시해두는 건, 나중에 모델별로 실제로 달라질 경우 recipe.json 하나만
# 보면 바로 알 수 있게 하기 위함.
RECIPE_PLACEMENTS = {
    "MODEL_A": [
        {"extra_holes": 1, "hole_index": 0, "bolt": "bolt_1"},
        {"extra_holes": 2, "hole_index": 3, "bolt": "bolt_2"},
    ],
    "MODEL_B": [
        {"extra_holes": 1, "hole_index": 0, "bolt": "bolt_1"},
        {"extra_holes": 1, "hole_index": 2, "bolt": "bolt_1"},
    ],
    "MODEL_C": [
        {"extra_holes": 2, "hole_index": 1, "bolt": "bolt_2"},
    ],
}
MOTHER_HOLE_COUNT = 5
# ⚠️ label_recipe_bolts.py의 전체 프레임 블롭 기준(10~20/21~31, 사이 여백)과는 다르다.
# 여기서는 접합점 한 곳만 국소 중앙값(median) 샘플링을 하는데, 실측 30장(model_a/b/c)
# 결과 주황은 hue 12~17, 노랑은 hue 19~29로 나와서 그 경계인 18에 딱 붙여야 정확히
# 갈린다 (label_recipe_bolts.py 기준의 20/21 경계를 그대로 쓰면 노랑 쪽 일부가 20 근처로
# 내려와 주황으로 잘못 갈림 — 실측으로 교정함).
HSV_RANGES = {
    "bolt_2": ((0, 100, 60), (18, 255, 255)),    # 주황
    "bolt_1": ((18, 100, 60), (35, 255, 255)),   # 노랑
}
JOINT_SAMPLE_RADIUS_FACTOR = 0.7   # 구멍 반경의 이 비율만큼 안쪽만 샘플링 (테두리 잡음 회피)
JOINT_COLORFUL_MIN_RATIO = 0.15    # 샘플 영역 중 이 비율 이상이 채도 있는 픽셀이어야 "뭔가 꽂혀있음"으로 판정

# ⚠️ 아래 임계값들은 실측 사진 100장(model_a/b/c)으로 튜닝한 값.
MIN_BAR_AREA_RATIO = 0.003    # 전체 프레임 대비 최소 나무 구조물 면적 비율 (노이즈 제외)
MIN_HOLE_AREA_RATIO = 0.0008  # 구멍 vs 나무결 장식 무늬(area_ratio<=0.00035) 구분용
HOLE_CIRCULARITY_MIN = 0.35   # 모서리/그림자에 걸친 구멍은 원형도가 낮게 나옴(실측 0.38~0.40)
MOTHER_BAND_WIDTH_RATIO = 0.6  # 이 비율 이상 넓은 행들을 "mother_part 몸통"으로 간주
# ⚠️ 세로 막대와 mother_part가 만나는 지점은 살짝 둥글게 이어져서, mother_top 바로 위
# 한두 줄은 두 세로 막대가 서로 픽셀로 이어져(다리처럼 붙어) connectedComponents가
# 하나로 묶어버린다 (실측 확인함) — 그 전이 구간만큼 더 위에서 잘라야 진짜로 분리된다.
MOTHER_TRANSITION_MARGIN_RATIO = 0.03  # 이미지 높이의 이 비율만큼 mother_top보다 더 위에서 자름

# 회전 보정 관련 파라미터
ROTATION_LINE_TOL_PX = 16        # 직선 피팅 시 이 거리(px) 이내 점을 "그 직선 위"로 간주
ROTATION_MIN_INLIERS = 3         # mother_part 축으로 인정할 최소 구멍 개수
ROTATION_SKIP_DEG = 3.0          # 이보다 작은 각도는 이미 수평이라 보고 회전 생략


def _circularity(cnt) -> float:
    area = cv2.contourArea(cnt)
    perimeter = cv2.arcLength(cnt, True)
    if perimeter == 0:
        return 0.0
    return float(4 * np.pi * area / (perimeter ** 2))


def _centroid(cnt):
    m = cv2.moments(cnt)
    if m["m00"] == 0:
        return None
    return (m["m10"] / m["m00"], m["m01"] / m["m00"])


def find_bar_and_holes(image, area_ref=None):
    """
    나무 구조물의 (가장 큰) 외곽 컨투어 하나와, 그 안의 "빈" 구멍 컨투어 리스트를 찾는다.
    area_ref: 면적 비율(min_bar_area 등) 계산 기준 픽셀 수. 회전 보정을 거치면 캔버스가
    커져서(회전한 사각형을 안 잘리게 담으려고 확장됨) image.shape 기준으로 비율을 다시
    계산하면 같은 크기의 구멍도 비율이 작아져 기준 미달로 빠질 수 있다 — 그래서 항상
    회전 전 원본 이미지의 픽셀 수를 넘겨서 기준을 고정한다. 생략하면 image 자체를 기준으로 함.
    Returns: (bar_contour_or_None, empty_hole_contours)
    """
    h_img, w_img = image.shape[:2]
    ref = area_ref if area_ref is not None else (h_img * w_img)
    min_bar_area = MIN_BAR_AREA_RATIO * ref
    min_hole_area = MIN_HOLE_AREA_RATIO * ref

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((3, 3), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, hierarchy = cv2.findContours(thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or not contours:
        return None, []
    hierarchy = hierarchy[0]

    top_level = [(i, cnt) for i, cnt in enumerate(contours) if hierarchy[i][3] == -1]
    top_level = [(i, cnt) for i, cnt in top_level if cv2.contourArea(cnt) >= min_bar_area]
    if not top_level:
        return None, []
    i, bar_cnt = max(top_level, key=lambda ic: cv2.contourArea(ic[1]))

    empty_holes = []
    child = hierarchy[i][2]
    while child != -1:
        child_cnt = contours[child]
        if (cv2.contourArea(child_cnt) >= min_hole_area
                and _circularity(child_cnt) >= HOLE_CIRCULARITY_MIN):
            empty_holes.append(child_cnt)
        child = hierarchy[child][0]

    return bar_cnt, empty_holes


def estimate_mother_angle(hole_centroids):
    """
    구멍 중심점들 중 가장 많은 점이 한 직선 위에 있는 조합(=mother_part의 5구멍 축)을
    찾아 그 직선의 각도를 반환한다 (라디안, -90~90도 범위로 정규화).
    mother_part는 구멍이 최소 3~4개 남아 일직선을 이루고, 세로 막대는 최대 2개뿐이라
    점 개수로 자연히 구분된다.
    Returns: (angle_rad, inlier_count)
    """
    pts = np.array(hole_centroids, dtype=np.float64)
    n = len(pts)
    if n < 2:
        return 0.0, 0

    best_inliers, best_count = None, 0
    for a in range(n):
        for b in range(a + 1, n):
            p1, p2 = pts[a], pts[b]
            d = p2 - p1
            length = np.hypot(d[0], d[1])
            if length < 1e-3:
                continue
            ux, uy = d[0] / length, d[1] / length
            nx, ny = -uy, ux  # 법선벡터
            dist = np.abs((pts[:, 0] - p1[0]) * nx + (pts[:, 1] - p1[1]) * ny)
            inliers = np.where(dist < ROTATION_LINE_TOL_PX)[0]
            if len(inliers) > best_count:
                best_count = len(inliers)
                best_inliers = inliers

    if best_inliers is None or best_count < 2:
        return 0.0, 0

    inlier_pts = pts[best_inliers].astype(np.float32)
    vx, vy, _, _ = cv2.fitLine(inlier_pts, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
    angle = float(np.arctan2(vy, vx))
    if angle <= -np.pi / 2:
        angle += np.pi
    elif angle > np.pi / 2:
        angle -= np.pi
    return angle, best_count


def rotate_image(image, angle_rad):
    """이미지를 angle_rad(라디안)만큼 회전시킨다. 잘리지 않도록 캔버스를 확장한다."""
    h, w = image.shape[:2]
    center = (w / 2, h / 2)
    angle_deg = np.degrees(angle_rad)
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos_a, sin_a = abs(M[0, 0]), abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)
    M[0, 2] += new_w / 2 - center[0]
    M[1, 2] += new_h / 2 - center[1]
    return cv2.warpAffine(image, M, (new_w, new_h), borderValue=(0, 0, 0))


def sample_bolt_color_debug(image, cx, cy, radius):
    """
    (cx,cy) 중심 반경 radius 안쪽만 국소적으로 봐서 어떤 볼트 색인지 판정한다.
    Returns: dict {"name": "bolt_1"/"bolt_2"/"unknown"/None, "median_hue": float|None,
                   "colorful_ratio": float, "mean_s": float, "mean_v": float}
    라이브 디버그 화면에서 왜 오탐/미탐이 났는지 바로 보이게 원시 수치까지 반환한다.
    """
    h_img, w_img = image.shape[:2]
    x1, x2 = max(0, int(cx - radius)), min(w_img, int(cx + radius))
    y1, y2 = max(0, int(cy - radius)), min(h_img, int(cy + radius))
    patch = image[y1:y2, x1:x2]
    if patch.size == 0:
        return {"name": None, "median_hue": None, "colorful_ratio": 0.0, "mean_s": 0.0, "mean_v": 0.0}

    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    # ⚠️ 밝기 게인을 올려서 보정하면 채널별 클리핑 때문에 hue 자체가 틀어져서 더 나빠졌다
    # (실측 확인함). 대신 V 임계값을 낮춰서 어두운 사진도 채도(S)만으로 "색 있음"을 잡는다.
    colorful = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 15)
    ratio = float(colorful.sum()) / (patch.shape[0] * patch.shape[1])
    mean_s = float(hsv[:, :, 1].mean())
    mean_v = float(hsv[:, :, 2].mean())

    if ratio < JOINT_COLORFUL_MIN_RATIO:
        return {"name": None, "median_hue": None, "colorful_ratio": ratio, "mean_s": mean_s, "mean_v": mean_v}

    median_hue = float(np.median(hsv[:, :, 0][colorful]))
    name = "unknown"
    for cname, (lo, hi) in HSV_RANGES.items():
        if lo[0] <= median_hue <= hi[0]:
            name = cname
            break
    return {"name": name, "median_hue": median_hue, "colorful_ratio": ratio, "mean_s": mean_s, "mean_v": mean_v}


def sample_bolt_color(image, cx, cy, radius):
    """(cx,cy) 중심 반경 radius 안쪽만 국소적으로 봐서 어떤 볼트 색인지 판정한다 (이름만)."""
    return sample_bolt_color_debug(image, cx, cy, radius)["name"]


def find_mother_band(bar_contour, image_shape):
    """외곽 컨투어를 채운 마스크에서 mother_part 몸통(가장 넓은 가로 밴드)의 위/아래 y좌표."""
    h_img, w_img = image_shape[:2]
    mask = np.zeros((h_img, w_img), dtype=np.uint8)
    cv2.drawContours(mask, [bar_contour], -1, 255, -1)
    row_widths = (mask > 0).sum(axis=1)
    if row_widths.max() == 0:
        return None, None, mask
    mother_rows = np.where(row_widths >= MOTHER_BAND_WIDTH_RATIO * row_widths.max())[0]
    return int(mother_rows.min()), int(mother_rows.max()), mask


def _empty_result(display_image, rotation_deg=0.0):
    return {
        "vertical_signature": [], "mother_top": None, "mother_bottom": None, "bar_contour": None,
        "empty_hole_contours": [], "above_labels": None, "n_verticals": 0,
        "display_image": display_image, "rotation_deg": rotation_deg, "joint_checks": [],
        "n_detected_holes": 0,
    }


def analyze_frame(image):
    """
    Returns: dict {"vertical_signature", "mother_top", "bar_contour", "empty_hole_contours",
                   "above_labels", "n_verticals", "display_image", "rotation_deg"}
    display_image: 실제 분석에 쓰인 이미지 (회전 보정이 적용됐으면 회전된 이미지) —
    bar_contour/empty_hole_contours의 좌표는 전부 이 이미지 기준이다.
    """
    area_ref = image.shape[0] * image.shape[1]
    bar_contour, empty_holes = find_bar_and_holes(image, area_ref)
    if bar_contour is None:
        return _empty_result(image)

    centroids = [c for c in (_centroid(cnt) for cnt in empty_holes) if c is not None]
    angle_rad, inlier_count = estimate_mother_angle(centroids)
    angle_deg = float(np.degrees(angle_rad))

    working_image = image
    if abs(angle_deg) > ROTATION_SKIP_DEG and inlier_count >= ROTATION_MIN_INLIERS:
        working_image = rotate_image(image, angle_rad)
        bar_contour, empty_holes = find_bar_and_holes(working_image, area_ref)
        if bar_contour is None:
            return _empty_result(working_image, angle_deg)

    mother_top, mother_bottom, mask = find_mother_band(bar_contour, working_image.shape)
    if mother_top is None:
        return _empty_result(working_image, angle_deg)

    # ⚠️ 세로 막대가 mother_part 위쪽으로 붙을 수도, 아래쪽으로 붙을 수도 있다(사진마다
    # 방향이 다름 — 실측 확인함). 그래서 위/아래 양쪽 다 본다.
    margin = int(MOTHER_TRANSITION_MARGIN_RATIO * working_image.shape[0])
    cutoff_top = mother_top - margin
    cutoff_bottom = mother_bottom + margin

    outside_mask = mask.copy()
    outside_mask[cutoff_top:cutoff_bottom + 1, :] = 0
    n_labels, labels = cv2.connectedComponents(outside_mask)

    per_vertical = {}
    for cnt in empty_holes:
        c = _centroid(cnt)
        if c is None:
            continue
        cx, cy = c
        if cutoff_top <= cy <= cutoff_bottom:
            continue  # mother_part 밴드+전이 구간 — 세로 막대 카운트 제외
        label = labels[int(cy), int(cx)]
        if label == 0:
            continue
        per_vertical[label] = per_vertical.get(label, 0) + 1

    vertical_signature = sorted(per_vertical.values(), reverse=True)

    # 각 세로 막대의 접합점(=mother_part 밴드 안, 그 막대 x열) 위치에서 볼트 색을 확인한다.
    hole_radius = 20.0
    if empty_holes:
        areas = [cv2.contourArea(c) for c in empty_holes]
        hole_radius = float(np.sqrt(np.median(areas) / np.pi))

    band_center_y = (mother_top + mother_bottom) // 2

    joint_x_by_label = {}
    for label in per_vertical:
        ys, xs = np.where(labels == label)
        if len(xs) == 0:
            continue
        joint_x_by_label[label] = int(xs.mean())

    # mother_hole 인덱스(왼쪽부터 0,1,2,...)를 매기려면 5개 구멍 위치를 전부 알아야 한다.
    # 접합점(볼트로 막힘)은 joint_x로 이미 알고, 나머지는 mother 밴드 안의 "빈 구멍"들이다.
    # ⚠️ 볼트 머리의 육각 소켓(홈)이 그 자체로 작은 "구멍"처럼 잡혀서 접합점 바로 옆에
    # 가짜 슬롯이 하나 더 생기는 경우가 있다 (실측 확인함) — 접합점과 너무 가까운
    # 후보는 그 소켓으로 보고 제외한다.
    joint_xs = list(joint_x_by_label.values())
    band_empty_xs = []
    for cnt in empty_holes:
        c = _centroid(cnt)
        if c is None:
            continue
        cx, cy = c
        if not (mother_top <= cy <= mother_bottom):
            continue
        if any(abs(cx - jx) < hole_radius for jx in joint_xs):
            continue  # 접합점 볼트의 육각 소켓 — 별도 구멍이 아님
        band_empty_xs.append(cx)
    all_hole_xs = sorted(band_empty_xs + joint_xs)
    n_detected_holes = len(all_hole_xs)

    def _hole_index(x):
        # 가장 가까운 슬롯을 찾아 왼쪽부터 0,1,2,...로 매김
        return int(np.argmin([abs(x - hx) for hx in all_hole_xs]))

    joint_checks = []
    for label, extra_holes in per_vertical.items():
        joint_x = joint_x_by_label.get(label)
        if joint_x is None:
            continue
        color_info = sample_bolt_color_debug(working_image, joint_x, band_center_y, hole_radius * JOINT_SAMPLE_RADIUS_FACTOR)
        joint_checks.append({
            "extra_holes": extra_holes,
            "x": joint_x,
            "y": band_center_y,
            "radius": hole_radius * JOINT_SAMPLE_RADIUS_FACTOR,
            "detected": color_info["name"],
            "median_hue": color_info["median_hue"],
            "colorful_ratio": color_info["colorful_ratio"],
            "hole_index": _hole_index(joint_x) if n_detected_holes == MOTHER_HOLE_COUNT else None,
        })

    return {
        "vertical_signature": vertical_signature,
        "mother_top": mother_top,
        "mother_bottom": mother_bottom,
        "bar_contour": bar_contour,
        "empty_hole_contours": empty_holes,
        "above_labels": labels,
        "n_verticals": n_labels - 1,
        "display_image": working_image,
        "rotation_deg": angle_deg,
        "joint_checks": joint_checks,
        "n_detected_holes": n_detected_holes,
    }


def classify_model(image):
    """
    Returns: (model_name_or_None, message, analysis_dict)
    구조(구멍 위치 개수)가 어떤 모델과 일치해도, RECIPE_PLACEMENTS와 대조해 볼트 색이나
    접합 위치가 틀리면 NG로 판정한다 — 부품 자체는 맞아도 엉뚱한 볼트를 쓰거나 엉뚱한
    구멍에 꽂은 경우를 잡기 위함.
    """
    analysis = analyze_frame(image)
    observed = analysis["vertical_signature"]

    matched_model = None
    for model_name, sig in MODEL_SIGNATURES.items():
        if observed == sig:
            matched_model = model_name
            break

    if matched_model is None:
        best_model, best_score = None, None
        for model_name, sig in MODEL_SIGNATURES.items():
            score = abs(len(observed) - len(sig)) + abs(sum(observed) - sum(sig))
            if best_score is None or score < best_score:
                best_model, best_score = model_name, score
        msg = (f"어떤 모델과도 일치하지 않음 (세로 막대별 위쪽 구멍 개수: {observed}, "
               f"회전보정 {analysis['rotation_deg']:.1f}도). "
               f"{best_model}(기대: {MODEL_SIGNATURES[best_model]})과 가장 유사")
        return None, msg, analysis

    ok, problem_msg = _check_placements(matched_model, analysis)
    if not ok:
        msg = f"{matched_model} 형태는 맞지만 배치 오류 — {problem_msg}"
        return None, msg, analysis

    msg = (f"{matched_model} 확인됨 (세로 막대별 위쪽 구멍 개수: {observed}, "
           f"회전보정 {analysis['rotation_deg']:.1f}도, 볼트 색상/위치 정상)")
    return matched_model, msg, analysis


def _check_placements(model_name, analysis):
    """
    RECIPE_PLACEMENTS[model_name]의 (구멍 개수, mother_hole 인덱스, 볼트 색)과 실제 접합점이
    맞는지 확인한다. 같은 부품이라도 모델마다 정해진 볼트 색이 다를 수 있어서(예: Model A의
    part_3hole=bolt_2, Model C의 part_3hole=bolt_1) 색과 위치를 같이, 모델별로 확인한다.
    ⚠️ 회전 보정은 mother_part를 수평으로만 돌려놓을 뿐, 어느 쪽 끝이 "왼쪽 0번"인지는
    (180도 뒤집혀 있을 수 있어서) 알 수 없다. 그래서 "감지된 순서 그대로"와 "반대로
    (n-1-index) 뒤집어서" 두 가지 다 시도해서, 하나라도 기대와 전부 일치하면 통과시킨다.
    위치를 아예 못 구했으면(구멍 5개를 다 못 찾음) 색상만이라도 확인한다.
    Returns: (ok: bool, message: str)
    """
    joint_checks = analysis["joint_checks"]
    expected = RECIPE_PLACEMENTS[model_name]
    position_known = analysis["n_detected_holes"] == MOTHER_HOLE_COUNT

    def _try(mirror):
        remaining = list(expected)
        for jc in joint_checks:
            idx = jc["hole_index"]
            if position_known:
                if idx is None:
                    return False
                if mirror:
                    idx = (MOTHER_HOLE_COUNT - 1) - idx
            match = next(
                (e for e in remaining if e["extra_holes"] == jc["extra_holes"]
                 and jc["detected"] == e["bolt"]
                 and (not position_known or e["hole_index"] == idx)),
                None,
            )
            if match is None:
                return False
            remaining.remove(match)
        return not remaining

    if _try(mirror=False) or (position_known and _try(mirror=True)):
        return True, ""

    problems = []
    for jc in joint_checks:
        # 이 접합점과 같은 extra_holes를 쓰는 기대 배치를 찾아 무엇이 다른지 설명
        candidates = [e for e in expected if e["extra_holes"] == jc["extra_holes"]]
        if not candidates:
            problems.append(f"구멍{jc['extra_holes']}개짜리 막대는 {model_name}에 없어야 함")
            continue
        exp = candidates[0]
        if jc["detected"] is None:
            problems.append(f"구멍{jc['extra_holes']}개짜리 막대 접합점에 볼트가 없음(기대: {exp['bolt']})")
        elif jc["detected"] != exp["bolt"]:
            problems.append(f"구멍{jc['extra_holes']}개짜리 막대 접합점: {exp['bolt']} 자리에 {jc['detected']} 사용됨")
        elif position_known and jc["hole_index"] not in (exp["hole_index"], MOTHER_HOLE_COUNT - 1 - exp["hole_index"]):
            problems.append(f"구멍{jc['extra_holes']}개짜리 막대가 {jc['hole_index']}번 자리(기대: {exp['hole_index']}번)")
    return False, "; ".join(problems) if problems else "원인 불명(배치 불일치)"


def _draw_debug(image, analysis):
    """⚠️ analysis['display_image'] 기준 좌표계다 — 회전 보정이 적용됐으면 원본이 아니라
    회전된 이미지 위에 그린다 (그래야 컨투어 좌표가 맞다)."""
    vis = analysis["display_image"].copy()
    if analysis["bar_contour"] is not None:
        cv2.drawContours(vis, [analysis["bar_contour"]], -1, (255, 0, 0), 2)
    if analysis["mother_top"] is not None:
        h_img, w_img = vis.shape[:2]
        cv2.line(vis, (0, analysis["mother_top"]), (w_img, analysis["mother_top"]), (0, 0, 255), 1)
        cv2.line(vis, (0, analysis["mother_bottom"]), (w_img, analysis["mother_bottom"]), (0, 0, 255), 1)
    for cnt in analysis["empty_hole_contours"]:
        c = _centroid(cnt)
        if c is None:
            continue
        cx, cy = int(c[0]), int(c[1])
        is_vertical = (analysis["mother_top"] is not None
                       and not (analysis["mother_top"] <= cy <= analysis["mother_bottom"]))
        color = (0, 255, 0) if is_vertical else (128, 128, 128)
        cv2.circle(vis, (cx, cy), 6, color, 2)
    for jc in analysis.get("joint_checks", []):
        # ⚠️ 여기선 "어떤 모델인지" 모르기 때문에(_check_placements가 classify_model
        # 단계에서 모델별로 판정함) 정오답 색이 아니라 그냥 검출 여부(있음/없음)만 표시.
        color = (0, 255, 255) if jc["detected"] else (0, 0, 255)
        # 샘플링에 실제로 쓴 원(반경)을 그대로 그려서 어디를 봤는지 바로 보이게 함
        cv2.circle(vis, (jc["x"], jc["y"]), int(jc["radius"]), (255, 0, 255), 1)
        cv2.drawMarker(vis, (jc["x"], jc["y"]), color, cv2.MARKER_TILTED_CROSS, 16, 2)
        hue_str = f"{jc['median_hue']:.0f}" if jc["median_hue"] is not None else "-"
        line1 = f"{jc['detected']} idx={jc['hole_index']}"
        line2 = f"hue={hue_str} colorful={jc['colorful_ratio']:.2f}"
        cv2.putText(vis, line1, (jc["x"] + 14, jc["y"] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.putText(vis, line2, (jc["x"] + 14, jc["y"] + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    cv2.putText(vis, f"vertical_signature={analysis['vertical_signature']} rotation={analysis['rotation_deg']:.1f}deg",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return vis


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="완성된 조립체 사진을 룰베이스(구멍 위치)로 Model A/B/C 분류")
    parser.add_argument("--input", required=True, help="조립체 사진 경로")
    parser.add_argument("--debug-output", default=None, help="구멍/막대 검출 결과를 그린 디버그 이미지 저장 경로")
    args = parser.parse_args()

    image = imread_unicode(Path(args.input))
    if image is None:
        print(f"[오류] 이미지를 읽을 수 없음: {args.input}", flush=True)
        return

    model, message, analysis = classify_model(image)
    print(f"분류 결과: {model or 'NG'}", flush=True)
    print(message, flush=True)

    if args.debug_output:
        vis = _draw_debug(image, analysis)
        imwrite_unicode(Path(args.debug_output), vis)
        print(f"디버그 이미지 저장: {args.debug_output}", flush=True)


if __name__ == "__main__":
    main()
