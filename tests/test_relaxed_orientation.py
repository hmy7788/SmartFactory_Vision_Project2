"""config/rtdetr_live.json이 켜는 옵션(좌우 뒤집힌 번호, 큰 각도)과, 부품은 반드시 Mother
"위쪽"에만 달려야 한다(아래쪽=NG)는 기본 규칙, 그리고 진짜 180도 회전(번호가 뒤집히면서
동시에 위/아래도 같이 뒤집히는 경우)만은 예외로 인정하는 evaluate_symmetric의 동작을 확인한다.
"""
import math

import pytest

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.contracts.inspection import Status
from src.process.recipe import Placement, Recipe, load_recipe

DEFAULT = load_config("config/mvp.json")
RELAXED = load_config("config/rtdetr_live.json")
BELOW_OK = {**RELAXED, "allow_parts_below": True}   # 아래쪽 부품을 아예 허용하는 opt-in 플래그 단독 검증용
RECIPE_3 = load_recipe("config/recipes/recipe_3.json")   # H2: bolt_2 + part_3hole
RECIPE_1 = load_recipe("config/recipes/recipe_1.json")   # H1: bolt_1+part_2hole, H4: bolt_2+part_3hole
WIDTH = 540.0


def scene(recipe, config, angle_deg=0.0, below=False, mirrored=False, center=(640.0, 360.0)):
    """레시피대로 정확히 조립된 장면(검출 목록)을 엔진 기하 공식 그대로 만든다."""
    a = math.radians(angle_deg)
    u, v = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    detections = [OBBDetection("mother", "mother_part", 0.95, center, WIDTH, 100.0, a)]
    side = 1 if below else -1   # -v가 mother-local 위쪽
    for i, placement in enumerate(recipe.placements):
        hole = 6 - placement.mother_hole if mirrored else placement.mother_hole
        alpha = config["hole_alphas"][hole - 1]
        point = (center[0] + alpha * WIDTH * u[0], center[1] + alpha * WIDTH * u[1])
        spec = config["part_rois"][placement.part]
        part_center = (point[0] + side * spec["offset_ratio"] * WIDTH * v[0],
                       point[1] + side * spec["offset_ratio"] * WIDTH * v[1])
        detections.append(OBBDetection(f"bolt{i}", placement.bolt, 0.9, point, 40.0, 40.0, 0.0))
        detections.append(OBBDetection(f"part{i}", placement.part, 0.9, part_center,
                                       spec["length_ratio"] * WIDTH, spec["width_ratio"] * WIDTH, a + math.pi / 2))
    return detections


def final_snapshot(recipe, config, detections):
    service = InspectionService(config, recipe)
    snapshot = None
    for i in range(80):
        snapshot = service.update(DetectionFrame(i, i * 50.0, tuple(detections)))
    return snapshot


def codes(snapshot):
    return {issue.code for issue in snapshot.candidate.issues}


@pytest.mark.parametrize("config", [DEFAULT, RELAXED])
def test_part_below_mother_is_ng_by_default(config):
    """부품이 Mother 아래쪽에 달리면(다른 부품/구멍번호는 정상), 각도·좌우뒤집힘 완화 여부와
    무관하게 기본값에서는 NG다."""
    snapshot = final_snapshot(RECIPE_3, config, scene(RECIPE_3, config, below=True))
    assert snapshot.status == Status.NG and "PART_WRONG_SIDE" in codes(snapshot)


def test_allow_parts_below_flag_accepts_part_below_mother():
    """opt-in(allow_parts_below=True)이면 회전 없이도 아래쪽 부착을 그대로 허용한다."""
    assert final_snapshot(RECIPE_3, BELOW_OK, scene(RECIPE_3, BELOW_OK, below=True)).status == Status.PASS


def test_relaxed_config_still_accepts_part_above_mother():
    assert final_snapshot(RECIPE_3, RELAXED, scene(RECIPE_3, RELAXED)).status == Status.PASS


def test_relaxed_config_rejects_parts_mixed_above_and_below():
    """한 평면 구조물의 부품들은 물리적으로 전부 같은 쪽에만 붙을 수 있다 — RECIPE_1의 두
    부품(H1, H4)을 일부러 서로 반대쪽(하나는 위, 하나는 아래)에 두면, 둘 다 정확한 구멍
    번호에 있어도 최소 한쪽은 PART_WRONG_SIDE로 NG여야 한다."""
    center, u, v = (640.0, 360.0), (1.0, 0.0), (0.0, 1.0)
    detections = [OBBDetection("mother", "mother_part", 0.95, center, WIDTH, 100.0, 0.0)]
    for i, (placement, side) in enumerate(zip(RECIPE_1.placements, (-1, 1))):
        alpha = RELAXED["hole_alphas"][placement.mother_hole - 1]
        point = (center[0] + alpha * WIDTH * u[0], center[1] + alpha * WIDTH * u[1])
        spec = RELAXED["part_rois"][placement.part]
        part_center = (point[0] + side * spec["offset_ratio"] * WIDTH * v[0],
                       point[1] + side * spec["offset_ratio"] * WIDTH * v[1])
        detections.append(OBBDetection(f"bolt{i}", placement.bolt, 0.9, point, 40.0, 40.0, 0.0))
        detections.append(OBBDetection(f"part{i}", placement.part, 0.9, part_center,
                                       spec["length_ratio"] * WIDTH, spec["width_ratio"] * WIDTH, math.pi / 2))
    snapshot = final_snapshot(RECIPE_1, RELAXED, detections)
    assert snapshot.status == Status.NG and "PART_WRONG_SIDE" in codes(snapshot)


@pytest.mark.parametrize("recipe", [RECIPE_3, RECIPE_1])
def test_180_degree_rotation_passes_by_default(recipe):
    """진짜 180도 회전(전체가 한 덩어리로 돌아감)은 구멍 번호와 위/아래가 항상 같이
    뒤집힌다 — allow_parts_below 없이도 evaluate_symmetric의 미러 가설이 이걸 그대로
    인정해야 한다 (좌우만 뒤집히고 위/아래는 그대로인 경우와 구별해야 함, 아래 참고)."""
    snapshot = final_snapshot(recipe, RELAXED, scene(recipe, RELAXED, mirrored=True, below=True))
    assert snapshot.status == Status.PASS
    assert snapshot.geometry["hole_numbering"] == "mirrored"


def test_mirrored_numbering_without_side_flip_is_still_ng():
    """구멍 번호만 뒤집히고 위/아래는 그대로인 조합(진짜 180도 회전이라면 불가능한 조합)은
    미러 가설로도 구제되지 않는다 — evaluate_symmetric이 미러 가설엔 반드시 "아래쪽"까지
    같이 요구하기 때문."""
    snapshot = final_snapshot(RECIPE_3, RELAXED, scene(RECIPE_3, RELAXED, mirrored=True))
    assert snapshot.status == Status.NG


def test_default_config_rejects_mirrored_hole_numbering():
    snapshot = final_snapshot(RECIPE_3, DEFAULT, scene(RECIPE_3, DEFAULT, mirrored=True))
    assert snapshot.status == Status.NG


def test_rotated_assembly_at_an_angle_and_mirrored_passes():
    detections = scene(RECIPE_1, RELAXED, angle_deg=-40.0, below=True, mirrored=True)
    assert final_snapshot(RECIPE_1, RELAXED, detections).status == Status.PASS


def test_large_mother_angle_rejected_by_default_and_accepted_when_relaxed():
    default = final_snapshot(RECIPE_3, DEFAULT, scene(RECIPE_3, DEFAULT, angle_deg=40.0))
    assert default.status == Status.HOLD and "MOTHER_ANGLE_OUT_OF_RANGE" in codes(default)
    assert final_snapshot(RECIPE_3, RELAXED, scene(RECIPE_3, RELAXED, angle_deg=40.0)).status == Status.PASS


@pytest.mark.parametrize("wrong_hole", [1, 3])
def test_genuinely_wrong_hole_is_still_ng_when_relaxed(wrong_hole):
    wrong = Recipe("wrong", (Placement(wrong_hole, "bolt_2", "part_3hole"),))
    snapshot = final_snapshot(RECIPE_3, RELAXED, scene(wrong, RELAXED))
    assert snapshot.status == Status.NG
    assert "UNEXPECTED_COMPONENT" in codes(snapshot)


def test_wrong_bolt_color_is_still_ng_when_relaxed():
    detections = [d if d.class_name != "bolt_2" else
                  OBBDetection(d.detection_id, "bolt_1", d.confidence, d.center_xy, d.width, d.height, d.angle_rad)
                  for d in scene(RECIPE_3, RELAXED, below=True)]
    snapshot = final_snapshot(RECIPE_3, RELAXED, detections)
    # 재료 게이트가 먼저 막는다 (주황 볼트가 없고 노랑 볼트가 불필요하게 있음)
    assert snapshot.status == Status.NG and "MATERIAL_UNEXPECTED" in codes(snapshot)
