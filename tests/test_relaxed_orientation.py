"""config/rtdetr_live.json이 켜는 옵션(위/아래 부품, 좌우 뒤집힌 번호, 큰 각도)과
기본 설정(config/mvp.json)의 원래 동작이 유지되는지 확인한다."""
import math

import pytest

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.contracts.inspection import Status
from src.process.recipe import Placement, Recipe, load_recipe

DEFAULT = load_config("config/mvp.json")
RELAXED = load_config("config/rtdetr_live.json")
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


def test_default_config_keeps_original_up_only_behavior():
    snapshot = final_snapshot(RECIPE_3, DEFAULT, scene(RECIPE_3, DEFAULT, below=True))
    assert snapshot.status == Status.HOLD and "AMBIGUOUS_ASSOCIATION" in codes(snapshot)


def test_relaxed_config_accepts_part_below_mother():
    assert final_snapshot(RECIPE_3, RELAXED, scene(RECIPE_3, RELAXED, below=True)).status == Status.PASS


def test_relaxed_config_still_accepts_part_above_mother():
    assert final_snapshot(RECIPE_3, RELAXED, scene(RECIPE_3, RELAXED)).status == Status.PASS


@pytest.mark.parametrize("recipe", [RECIPE_3, RECIPE_1])
def test_relaxed_config_accepts_mirrored_hole_numbering(recipe):
    snapshot = final_snapshot(recipe, RELAXED, scene(recipe, RELAXED, mirrored=True))
    assert snapshot.status == Status.PASS
    assert snapshot.geometry["hole_numbering"] == "mirrored"


def test_default_config_rejects_mirrored_hole_numbering():
    snapshot = final_snapshot(RECIPE_3, DEFAULT, scene(RECIPE_3, DEFAULT, mirrored=True))
    assert snapshot.status == Status.NG


def test_rotated_assembly_on_far_side_and_mirrored_passes():
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
