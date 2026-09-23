"""레시피 판정 매트릭스 — 모델 없이 "레시피대로 맞게 판정하나"를 끝까지 돌려 본다.

    python -m scripts.check_recipes            # 표를 찍는다 (recipe_1·2·3 × 상황 15가지)
    python -m scripts.check_recipes recipe_2   # 한 레시피만

모델이 낼 것과 같은 형식으로 만든다: 한글 클래스명(볼트_주황 …)을 가진 가짜 ultralytics Results
→ src/vision/detection_adapter.from_ultralytics (class_mapping.json 적용) → DetectionFrame → 코어.
그러니까 여기서 통과하면, 나중에 진짜 모델이 같은 자리에 같은 클래스로 박스를 그리는 한 판정은 같다.

시간은 가짜다 — 100ms 간격의 타임스탬프를 붙여 안정화 창(재료 1000ms · 조립 400ms)을 넘긴다. 잠들지 않는다.
"""
from __future__ import annotations

import json
import sys
from math import pi
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.process.recipe import load_recipe
from src.vision.detection_adapter import from_ultralytics

ROOT = Path(__file__).resolve().parents[1]
MAPPING = json.loads((ROOT / "config/class_mapping.json").read_text(encoding="utf-8"))
KOREAN = {v: k for k, v in MAPPING.items()}          # 영문 → 모델이 내는 한글 이름
NAMES = {i: k for i, k in enumerate(MAPPING)}        # 가짜 모델의 클래스 인덱스표
IDX = {k: i for i, k in NAMES.items()}
MOTHER = (600.0, 700.0, 1000.0, 160.0)               # 화면 좌표: 중심 x,y · 폭 · 높이 (scripts/demo_data.py 와 같은 기하)
PART_LEN = {"part_2hole": 320.0, "part_3hole": 500.0}


# ── 가짜 ultralytics Results (어댑터가 요구하는 .obb.xywhr/.cls/.conf 와 .names 만) ──
class _T:
    def __init__(self, rows): self.rows = rows
    def cpu(self): return self
    def tolist(self): return self.rows


class _Result:
    names = NAMES

    def __init__(self, boxes):        # boxes: [(영문클래스, cx, cy, w, h, angle_rad, conf)]
        class Obb: pass
        self.obb = Obb()
        self.obb.xywhr = _T([[b[1], b[2], b[3], b[4], b[5]] for b in boxes])
        self.obb.cls = _T([IDX[KOREAN[b[0]]] for b in boxes])
        self.obb.conf = _T([b[6] for b in boxes])


# ── 장면 만들기 ──
def hole_x(config, hole):
    return MOTHER[0] + config["hole_alphas"][hole - 1] * MOTHER[2]


def mother(angle_deg=0.0):
    return ("mother_part", MOTHER[0], MOTHER[1], MOTHER[2], MOTHER[3], angle_deg * pi / 180, 0.97)


def bolt(config, hole, cls):
    return (cls, hole_x(config, hole), MOTHER[1], 80.0, 80.0, 0.0, 0.92)


def part(config, hole, cls, tilt_deg=0.0):
    length = PART_LEN[cls]
    x = hole_x(config, hole)
    return (cls, x, MOTHER[1] - length / 2 + 40, length, 90.0, pi / 2 + tilt_deg * pi / 180, 0.90)


def placed(config, recipe, skip=(), swap_bolt=None, swap_part=None, tilt=None):
    """레시피대로 꽂은 장면. skip=빼먹을 자리, swap_bolt/part={자리: 다른종류}, tilt={자리: 각도}"""
    out = []
    for p in recipe.placements:
        if p.mother_hole in skip:
            continue
        out.append(bolt(config, p.mother_hole, (swap_bolt or {}).get(p.mother_hole, p.bolt)))
        out.append(part(config, p.mother_hole, (swap_part or {}).get(p.mother_hole, p.part), (tilt or {}).get(p.mother_hole, 0.0)))
    return out


def scattered(recipe, extra=None, drop=None):
    """재료 확인용 — Mother 에서 떨어진 자리에 흩어 놓는다. extra=하나 더, drop=하나 뺌"""
    out = []
    for k, p in enumerate(recipe.placements):
        if p.bolt != drop:
            out.append((p.bolt, 120 + k * 400, 120, 80, 80, 0.0, 0.9))
        if p.part != drop:
            out.append((p.part, 330 + k * 400, 120, PART_LEN[p.part], 90, 0.0, 0.86))
    if extra:
        out.append((extra, 980, 320, PART_LEN.get(extra, 80), 90 if extra in PART_LEN else 80, 0.3, 0.83))
    return out


# ── 코어에 넣기 ──
class Runner:
    """프레임을 만들어 코어에 넣는다. 100ms 간격 가짜 시각."""

    def __init__(self, config, recipe):
        self.config, self.recipe = config, recipe
        self.service = InspectionService(config, recipe)
        self.frame_id, self.ts = 0, 0

    def feed(self, boxes, ms):
        """같은 장면을 ms 동안 100ms 간격으로 넣고 마지막 snapshot 을 준다."""
        snap = None
        for _ in range(max(2, ms // 100)):
            self.frame_id += 1; self.ts += 100
            frame = from_ultralytics(_Result(boxes), self.frame_id, self.ts, MAPPING)
            snap = self.service.update(frame)
        return snap

    def to_assembling(self):
        """재료를 정확히 놓아 조립 단계로 넘긴 뒤, 부품을 치운 빈 Mother 상태로."""
        self.feed([mother()] + scattered(self.recipe), 1400)
        assert self.service.machine.phase.value == "ASSEMBLING", "재료 단계를 못 넘김"
        self.feed([mother()], 600)


def verdict(snap):
    """(phase, status, 대표 issue 코드[:H자리]) — 사람이 읽는 한 줄"""
    issues = [f"{i.code}" + (f":H{i.hole_id}" if i.hole_id else "") for i in snap.candidate.issues]
    return snap.phase.value, snap.status.value, issues[0] if issues else "—"


def cases(config, recipe):
    """(이름, 단계, 장면, 기대 status, 기대 issue 코드 prefix)"""
    pl = recipe.placements
    first, other = pl[0], (pl[1] if len(pl) > 1 else None)
    wrong_bolt = "bolt_2" if first.bolt == "bolt_1" else "bolt_1"
    wrong_part = "part_3hole" if first.part == "part_2hole" else "part_2hole"
    used = {p.mother_hole for p in pl}
    free_hole = next(h for h in (3, 2, 4, 1) if h not in used)      # 레시피에 없는 자리 (H5 제외)
    unexpected_material = "part_3hole" if all(p.part == "part_2hole" for p in pl) else ("bolt_2" if all(p.bolt == "bolt_1" for p in pl) else None)
    rows = [
        ("재료 정확히 다 놓음",         "재료", scattered(recipe),                          "READY",       "—"),
        ("재료 하나 부족",             "재료", scattered(recipe, drop=first.part),          "IN_PROGRESS", "MATERIAL_MISSING"),
        ("재료 같은 종류 하나 더",      "재료", scattered(recipe, extra=first.bolt),         "NG",          "MATERIAL_EXCESS"),
    ]
    if unexpected_material:
        rows.append(("재료에 레시피 밖 종류 섞임", "재료", scattered(recipe, extra=unexpected_material), "NG", "MATERIAL_UNEXPECTED"))
    rows += [
        ("빈 Mother (아직 안 꽂음)",   "조립", [],                                          "IN_PROGRESS", "MISSING_BOLT"),
        ("레시피대로 전부 꽂음",        "조립", placed(config, recipe),                      "PASS",        "—"),
        (f"H{first.mother_hole} 볼트 종류 틀림", "조립", placed(config, recipe, swap_bolt={first.mother_hole: wrong_bolt}), "NG", f"WRONG_BOLT:H{first.mother_hole}"),
        (f"H{first.mother_hole} 파트 종류 틀림", "조립", placed(config, recipe, swap_part={first.mother_hole: wrong_part}), "NG", f"WRONG_PART:H{first.mother_hole}"),
        (f"레시피에 없는 H{free_hole} 에 꽂음", "조립", placed(config, recipe) + [bolt(config, free_hole, first.bolt), part(config, free_hole, first.part)], "NG", f"UNEXPECTED_COMPONENT:H{free_hole}"),
        ("H5 에 볼트 꽂음 (금지 자리)", "조립", placed(config, recipe) + [bolt(config, 5, "bolt_1")], "NG", "UNEXPECTED_COMPONENT:H5"),
        (f"H{first.mother_hole} 파트 25° 비뚤게", "조립", placed(config, recipe, tilt={first.mother_hole: 25}), "NG", f"PART_ORIENTATION_ERROR:H{first.mother_hole}"),
        (f"H{first.mother_hole} 에 볼트 2개",   "조립", placed(config, recipe) + [bolt(config, first.mother_hole, first.bolt)], "NG", f"EXTRA_COMPONENT:H{first.mother_hole}"),
    ]
    if other:
        rows.append((f"H{other.mother_hole} 만 빠뜨림", "조립", placed(config, recipe, skip=(other.mother_hole,)), "IN_PROGRESS", f"MISSING_BOLT:H{other.mother_hole}"))
    rows += [
        ("Mother 26° 기울임",         "조립", "TILT",                                       "HOLD",        "MOTHER_ANGLE_OUT_OF_RANGE"),
        ("NG 였다가 바로잡음",          "조립", "FIX",                                        "PASS",        "—"),
    ]
    return rows


def run(recipe_id, config, verbose=True):
    recipe = load_recipe(ROOT / f"config/recipes/{recipe_id}.json")
    want = " · ".join(f"H{p.mother_hole} {p.bolt}+{p.part}" for p in recipe.placements)
    if verbose:
        print(f"\n━━ {recipe_id}   정답: {want}")
        print(f"   {'상황':28} {'단계':4} {'기대':12} {'실제':12} {'이유 (issue)':30} ")
    ok_all = True
    for name, stage, scene, want_status, want_issue in cases(config, recipe):
        r = Runner(config, recipe)
        if stage == "재료":
            snap = r.feed([mother()] + scene, 1400)
        else:
            r.to_assembling()
            if scene == "TILT":
                snap = r.feed([mother(26)] + placed(config, recipe), 600)
            elif scene == "FIX":
                r.feed([mother()] + placed(config, recipe, swap_bolt={recipe.placements[0].mother_hole: "bolt_2" if recipe.placements[0].bolt == "bolt_1" else "bolt_1"}), 800)
                assert r.service.machine.status.value == "NG"
                snap = r.feed([mother()] + placed(config, recipe), 800)
            else:
                snap = r.feed([mother()] + scene, 800)
        phase, status, issue = verdict(snap)
        # 재료 단계에서 READY 가 확정되면 코어는 곧장 조립 단계로 넘어가며 status 를 HOLD 로 비운다 → 전환 자체가 '맞음'
        got_status = "READY" if (stage == "재료" and phase == "ASSEMBLING") else status
        if got_status == "READY":
            issue = "→ 조립 단계로 자동 전환"
        ok = got_status == want_status and (want_issue == "—" or issue.startswith(want_issue))
        ok_all &= ok
        if verbose:
            mark = "✓" if ok else "✗"
            print(f" {mark} {name:28} {stage:4} {want_status:12} {got_status:12} {issue:30}")
    return ok_all


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    config = load_config(ROOT / "config/mvp.json")
    ids = argv or ["recipe_1", "recipe_2", "recipe_3"]
    results = {rid: run(rid, config) for rid in ids}
    bad = [k for k, v in results.items() if not v]
    print("\n" + ("전부 통과 — 레시피대로 판정합니다." if not bad else f"실패: {bad}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
