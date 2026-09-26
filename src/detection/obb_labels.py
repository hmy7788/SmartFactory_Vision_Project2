"""YOLO-OBB 라벨(.txt) 읽기·검사·각도 계산 — torch/ultralytics 없이 돈다. (데이터 준비·평가·테스트가 같이 쓴다)

라벨 한 줄:  `class x1 y1 x2 y2 x3 y3 x4 y4`  — 꼭짓점 4개, 0~1 정규화, 순서는 시계/반시계 아무거나.

클래스 번호는 팀 라벨 규약(auto_label_iconic.py · 로보플로우 프로젝트) 그대로다:
    0 볼트_주황=bolt_2   1 볼트_노랑=bolt_1   2 나무_5구멍=mother_part   3 나무_3구멍=part_3hole   4 나무_2구멍=part_2hole
data.yaml 에는 영문 이름(bolt_2 …)을 쓴다 — 코어(config/class_mapping.json 오른쪽)가 바로 받고, ultralytics 가 그리는
결과 그림(cv2)이 한글을 못 써서 '???' 로 나오는 것도 피한다. 한글 이름이 필요하면 --korean-names.

각도 규약은 코어(src/geometry/mother_frame.major_axis)와 같다: 긴 변 방향을 [-90°, 90°) 로 접는다.
막대(mother·part)는 180° 돌려도 같은 물체라 각도 오차는 min(d, 180-d) 로 잰다. 볼트는 육각이라 각도를 재지 않는다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

CLASS_NAMES = ("bolt_2", "bolt_1", "mother_part", "part_3hole", "part_2hole")
KOREAN_NAMES = ("볼트_주황", "볼트_노랑", "나무_5구멍", "나무_3구멍", "나무_2구멍")
BAR_CLASSES = ("mother_part", "part_3hole", "part_2hole")        # 각도가 뜻이 있는 부품
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp")


@dataclass(frozen=True)
class ObbLabel:
    class_id: int
    points: tuple[tuple[float, float], ...]        # 꼭짓점 4개, 정규화 좌표

    @property
    def xs(self): return [p[0] for p in self.points]

    @property
    def ys(self): return [p[1] for p in self.points]

    def to_line(self) -> str:
        return " ".join([str(self.class_id)] + [f"{v:.6f}" for p in self.points for v in p])


def parse_label_line(line: str, lineno: int = 0) -> ObbLabel:
    """한 줄 → ObbLabel. 형식이 틀리면 ValueError(줄 번호 포함). 5칸(AABB xywh)이면 OBB 가 아니라고 알려 준다."""
    parts = line.split()
    if len(parts) == 5:
        raise ValueError(f"{lineno}행: 5칸(class cx cy w h) — AABB 라벨입니다. OBB(꼭짓점 4개, 9칸)가 필요합니다")
    if len(parts) != 9:
        raise ValueError(f"{lineno}행: 9칸이어야 하는데 {len(parts)}칸")
    try:
        class_id = int(float(parts[0]))
        vals = [float(v) for v in parts[1:]]
    except ValueError:
        raise ValueError(f"{lineno}행: 숫자가 아닌 값: {line!r}") from None
    return ObbLabel(class_id, tuple((vals[i], vals[i + 1]) for i in range(0, 8, 2)))


def parse_label_file(path: str | Path) -> list[ObbLabel]:
    labels = []
    for i, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip():
            labels.append(parse_label_line(raw, i))
    return labels


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    n = len(points)
    return 0.5 * abs(sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n)))


def is_axis_aligned(points: Sequence[tuple[float, float]], eps: float = 1e-4) -> bool:
    """꼭짓점의 x 값과 y 값이 각각 2가지뿐이면 회전 없는 직사각형(AABB 를 OBB 형식으로 적은 것)."""
    xs = sorted(set(round(p[0] / eps) for p in points))
    ys = sorted(set(round(p[1] / eps) for p in points))
    return len(xs) <= 2 and len(ys) <= 2


def check_label(label: ObbLabel, n_classes: int = len(CLASS_NAMES), tol: float = 0.0) -> list[str]:
    """라벨 하나의 문제 목록(비어 있으면 정상). tol 만큼은 화면 밖으로 나가도 봐준다."""
    problems = []
    if not 0 <= label.class_id < n_classes:
        problems.append(f"클래스 번호 {label.class_id} (0~{n_classes - 1} 이어야 함)")
    lo, hi = -tol, 1 + tol
    if any(not (lo <= v <= hi) for p in label.points for v in p):
        problems.append("꼭짓점이 이미지 밖 (0~1 벗어남)")
    if polygon_area(label.points) < 1e-6:
        problems.append("넓이 0 (꼭짓점이 겹치거나 한 줄)")
    return problems


def clip_label(label: ObbLabel) -> ObbLabel:
    return ObbLabel(label.class_id, tuple((min(1.0, max(0.0, x)), min(1.0, max(0.0, y))) for x, y in label.points))


# ── 각도 ──────────────────────────────────────────────────────────────

def polygon_to_xywhr(points_px: Sequence[tuple[float, float]]) -> tuple[float, float, float, float, float]:
    """픽셀 꼭짓점 4개 → (cx, cy, w, h, angle_rad). cv2.minAreaRect 를 써서 직사각형이 아니어도 가장 가까운 회전 박스를 준다."""
    import cv2
    import numpy as np

    (cx, cy), (w, h), deg = cv2.minAreaRect(np.asarray(points_px, dtype=np.float32))
    return float(cx), float(cy), float(w), float(h), math.radians(deg)


def long_axis_angle(w: float, h: float, angle_rad: float) -> float:
    """긴 변 방향을 [-90°, 90°) 라디안으로 접는다 — src.geometry.mother_frame.major_axis 와 같은 규약."""
    if h > w:
        angle_rad += math.pi / 2
    return (angle_rad + math.pi / 2) % math.pi - math.pi / 2


def angle_error_deg(a_rad: float, b_rad: float) -> float:
    """긴 변 방향 둘의 차이(도). 막대는 180° 대칭이라 0~90 사이 값이 나온다."""
    d = abs(math.degrees(a_rad - b_rad)) % 180.0
    return min(d, 180.0 - d)


def points_to_pixels(points: Sequence[tuple[float, float]], width: int, height: int) -> list[tuple[float, float]]:
    return [(x * width, y * height) for x, y in points]


# ── 파일 이름 ─────────────────────────────────────────────────────────

_GROUP_RE = re.compile(r"(_frame\d.*|_\d.*|\.rf\..*)$")


def stem_group(stem: str) -> str:
    """파일 이름 → 촬영 묶음 (bolt, part, mother_part, model_a, recipe1_process, 2_hole, b …). val 을 떼어낼 때 묶음별 비율을 지킨다."""
    return _GROUP_RE.sub("", stem) or stem


def find_image(stem: str, image_dir: Path, exts: Iterable[str] = IMAGE_EXTS) -> Path | None:
    for ext in exts:
        for candidate in (image_dir / f"{stem}{ext}", image_dir / f"{stem}{ext.upper()}"):
            if candidate.exists():
                return candidate
    return None
