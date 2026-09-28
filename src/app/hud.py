"""
hud.py

라이브 검사 화면: 검출 박스 + 구멍(H1~H5) 링 + 한글 상태/안내 문구.

cv2.putText는 한글을 못 그려서(?로 나옴) 글자는 PIL(맑은 고딕)로 그린다. 도형(박스/링)은
cv2로 그리고, 글자만 프레임당 한 번 PIL 변환으로 처리한다.
"""

from collections import defaultdict

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.contracts.inspection import Phase, Status
from src.geometry.spatial import rectangle

KOR_CLASS = {
    "bolt_1": "노랑 볼트",
    "bolt_2": "주황 볼트",
    "mother_part": "Mother(5구 나무)",
    "part_2hole": "2구 나무조각",
    "part_3hole": "3구 나무조각",
}
CLASS_COLOR = {  # BGR
    "mother_part": (80, 200, 80),
    "bolt_1": (0, 230, 255),
    "bolt_2": (0, 140, 255),
    "part_2hole": (255, 200, 0),
    "part_3hole": (255, 0, 255),
}
PHASE_LABEL = {Phase.CHECK_MATERIALS: "1. 재료 확인", Phase.ASSEMBLING: "2. 조립 검사"}
STATUS_LABEL = {Status.READY: "재료 준비 완료", Status.IN_PROGRESS: "조립 중",
                Status.PASS: "정상 (조립 완료)", Status.NG: "오류 (NG)", Status.HOLD: "판정 대기"}
STATUS_COLOR = {Status.READY: (120, 255, 120), Status.IN_PROGRESS: (255, 210, 60),
                Status.PASS: (80, 255, 80), Status.NG: (255, 70, 70), Status.HOLD: (225, 225, 225)}
GUIDANCE_CODES = {"MATERIAL_MISSING", "MISSING_BOLT", "MISSING_PART"}
GUIDANCE_COLOR, ERROR_COLOR = (255, 210, 60), (255, 70, 70)
RING_COLOR = {"ok": (80, 220, 80), "missing": (0, 210, 255), "error": (60, 60, 255), "idle": (150, 150, 150)}  # BGR

FONT_CANDIDATES = ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc")


def josa(word, pair):
    """받침 유무에 맞는 조사 붙이기. pair는 '을/를', '이/가'처럼 (받침 있음)/(받침 없음)."""
    with_final, without_final = pair.split("/")
    last = word[-1]
    if "가" <= last <= "힣":
        return word + (with_final if (ord(last) - 0xAC00) % 28 else without_final)
    return word + without_final


def _kor(name):
    return KOR_CLASS.get(name, name)


def issue_message(issue, config):
    """Issue 코드를 사용자가 바로 따라 할 수 있는 한글 문장으로."""
    code, h = issue.code, issue.hole_id
    if code in ("MATERIAL_MISSING", "MATERIAL_EXCESS", "MATERIAL_UNEXPECTED"):
        name, _, need = issue.expected.partition(":")
        _, _, have = issue.observed.partition(":")
        label = {"MATERIAL_MISSING": "재료 부족", "MATERIAL_EXCESS": "재료 초과",
                 "MATERIAL_UNEXPECTED": "재료 불필요"}[code]
        return f"{label}: {_kor(name)} 필요 {need}개 / 현재 {have}개"
    if code == "MISSING_BOLT":
        return f"H{h}: {josa(_kor(issue.expected), '을/를')} 끼워주세요"
    if code == "MISSING_PART":
        return f"H{h}: {josa(_kor(issue.expected), '을/를')} 연결해주세요"
    if code == "WRONG_BOLT" or code == "WRONG_PART":
        return f"H{h}: {_kor(issue.expected)} 자리에 {josa(_kor(issue.observed), '이/가')} 있습니다"
    if code == "EXTRA_COMPONENT":
        return f"H{h}: {_kor(issue.expected)} 자리에 부품이 중복되어 있습니다 ({issue.observed})"
    if code == "UNEXPECTED_COMPONENT":
        return f"H{h}: 레시피에 없는 위치입니다 ({_kor(issue.observed)}) - 빼주세요"
    if code == "PART_ORIENTATION_ERROR":
        return f"H{h}: {josa(_kor(issue.expected), '이/가')} Mother와 수직이 아닙니다 - 바르게 맞춰주세요"
    if code == "MOTHER_NOT_FOUND":
        return "Mother(5구 나무)가 보이지 않습니다"
    if code == "MULTIPLE_MOTHERS":
        return "Mother가 여러 개 감지되었습니다"
    if code == "MOTHER_ANGLE_OUT_OF_RANGE":
        return f"Mother가 너무 기울어 있습니다 (±{config['max_mother_angle_deg']}° 이내로 놓아주세요)"
    if code == "AMBIGUOUS_ASSOCIATION":
        return "어느 구멍인지 불명확한 부품이 있습니다. 구멍에 정확히 맞춰주세요"
    if code == "FRAME_GAP":
        return "프레임이 끊겼습니다 (처리 속도 부족 또는 영상 정지)"
    if code == "OUT_OF_ORDER_FRAME":
        return "프레임 순서 오류"
    if code == "INPUT_UNAVAILABLE":
        return "입력 영상이 없습니다"
    return code


def recipe_text(recipe):
    parts = [f"H{p.mother_hole}: {_kor(p.bolt)} + {_kor(p.part)}" for p in recipe.placements]
    return "레시피: " + " / ".join(parts)


class Hud:
    def __init__(self, config):
        self.config = config
        self._fonts = {}

    def _font(self, size):
        if size not in self._fonts:
            for path in FONT_CANDIDATES:
                try:
                    self._fonts[size] = ImageFont.truetype(path, size)
                    break
                except OSError:
                    continue
            else:
                self._fonts[size] = ImageFont.load_default()
        return self._fonts[size]

    @staticmethod
    def _hole_states(snapshot, recipe, mirrored=False):
        """레시피 번호(H1~H5) 기준 상태. mirrored면 관측값(snapshot.observed)은 화면 번호라 6-h로 매핑."""
        issues_by_hole = defaultdict(list)
        for issue in snapshot.candidate.issues:
            issues_by_hole[issue.hole_id].append(issue)
        expected = {p.mother_hole: p for p in recipe.placements}
        states = {}
        for hole in range(1, 6):
            errors = [i for i in issues_by_hole.get(hole, []) if not i.code.startswith("MISSING_")]
            if errors:
                states[hole] = "error"
            elif hole in expected:
                seen = snapshot.observed.get(6 - hole if mirrored else hole, {})
                filled = bool(seen.get("bolt")) and bool(seen.get("part"))
                states[hole] = "ok" if filled and not issues_by_hole.get(hole) else "missing"
            else:
                states[hole] = "idle"
        return states

    def _text_lines(self, snapshot, recipe):
        status = snapshot.status
        label = STATUS_LABEL[status]
        if snapshot.candidate.status != Status.HOLD and not snapshot.stable:
            label += " (확인 중)"
        lines = [(f"{recipe.recipe_id}  |  {PHASE_LABEL[snapshot.phase]}", (255, 255, 255)),
                 (recipe_text(recipe), (255, 255, 255)),
                 (f"상태: {label}", STATUS_COLOR[status])]
        for issue in snapshot.candidate.issues[:5]:
            color = GUIDANCE_COLOR if issue.code in GUIDANCE_CODES else ERROR_COLOR
            lines.append((f"• {issue_message(issue, self.config)}", color))
        if len(snapshot.candidate.issues) > 5:
            lines.append((f"• 외 {len(snapshot.candidate.issues) - 5}건", (200, 200, 200)))
        return lines

    def draw(self, frame, snapshot, detection_frame, info, recipe, fps):
        out = frame.copy()
        threshold = self.config["confidence_threshold"]
        for d in detection_frame.detections:
            if d.confidence < threshold:
                continue
            polygon = np.array(rectangle(d.center_xy, d.width, d.height, d.angle_rad), np.int32)
            color = CLASS_COLOR[d.class_name]
            cv2.polylines(out, [polygon], True, color, 2)
            top = polygon[polygon[:, 1].argmin()]
            cv2.putText(out, f"{d.class_name} {d.confidence:.2f}", (int(top[0]), max(12, int(top[1]) - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        holes = snapshot.geometry.get("holes")
        if holes:
            # 좌우 뒤집힌 번호로 판정됐으면(mother는 대칭이라 반대쪽 끝에서 읽은 것) 링 라벨도 레시피 번호로.
            mirrored = snapshot.geometry.get("hole_numbering") == "mirrored"
            states = self._hole_states(snapshot, recipe, mirrored)
            radius = max(8, int(0.055 * snapshot.geometry["pose"]["width"]))
            for hole, (x, y) in holes.items():
                number = 6 - hole if mirrored else hole
                color = RING_COLOR[states[number]]
                cv2.circle(out, (int(x), int(y)), radius, color, 2)
                cv2.putText(out, f"H{number}", (int(x) - radius // 2, int(y) - radius - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        size = max(16, out.shape[0] // 32)
        font, small = self._font(size), self._font(max(13, size - 5))
        line_h = int(size * 1.35)
        pad = 10
        lines = self._text_lines(snapshot, recipe)
        panel_w = int(max(font.getlength(text) for text, _ in lines)) + 2 * pad
        panel_h = line_h * len(lines) + 2 * pad
        shade = out.copy()
        cv2.rectangle(shade, (0, 0), (min(panel_w, out.shape[1]), panel_h), (0, 0, 0), -1)
        out = cv2.addWeighted(shade, 0.55, out, 0.45, 0)

        image = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        y = pad
        for text, color in lines:
            draw.text((pad, y), text, font=font, fill=color, stroke_width=1, stroke_fill=(0, 0, 0))
            y += line_h
        footer = f"FPS {fps:.1f}   [1/2/3] 레시피   [n] 새 제품   [q] 종료"
        draw.text((pad, out.shape[0] - pad - line_h), footer, font=small, fill=(255, 255, 255),
                  stroke_width=1, stroke_fill=(0, 0, 0))
        angle = info.get("mother_angle_deg")
        angle_text = (f"mother 각도 {angle:.1f}° ({info['angle_source']})" if angle is not None
                      else f"mother 각도 없음 ({info['angle_source']})")
        draw.text((out.shape[1] - small.getlength(angle_text) - pad, out.shape[0] - pad - line_h),
                  angle_text, font=small, fill=(200, 200, 200), stroke_width=1, stroke_fill=(0, 0, 0))
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
