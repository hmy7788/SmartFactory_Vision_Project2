"""완성체 사진(aabb 의 model_a/b/c + 라벨)을 코어에 넣어 판정을 확인한다 — 모델 없이, 라벨 박스를 검출로 쓴다.

    python -m scripts.replay_photos ..\\aabb                 # AABB 그대로 (각도 0) — 똑바로 놓은 사진용
    python -m scripts.replay_photos ..\\aabb --refine        # OpenCV 각도 보정 — 삐뚤게 놓은 사진까지
    python -m scripts.replay_photos ..\\aabb --refine --max-angle 90 --draw out_dir   # 각도 제한 풀고 그림까지

사진마다: 자기 레시피(model_a→recipe_1 …)로 PASS 가 나는지, 다른 레시피로는 PASS 가 안 나는지.
"""
from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.process.recipe import load_recipe

ROOT = Path(__file__).resolve().parents[1]
NAMES = {0: "bolt_2", 1: "bolt_1", 2: "mother_part", 3: "part_3hole", 4: "part_2hole"}      # aabb/data.yaml 순서
PHOTO_RECIPE = {"model_a": "recipe_1", "model_b": "recipe_2", "model_c": "recipe_3"}


def label_detections(txt: Path, w: int, h: int):
    out = []
    for i, line in enumerate(txt.read_text().splitlines()):
        if not line.strip():
            continue
        c, cx, cy, bw, bh = line.split()[:5]
        out.append(OBBDetection(str(i), NAMES[int(c)], 0.95, (float(cx) * w, float(cy) * h), float(bw) * w, float(bh) * h, 0.0))
    return tuple(out)


def scattered(recipe):
    """재료 확인 단계를 넘기기 위한 가짜 재료 프레임 (사진과 무관)."""
    out = [OBBDetection("m", "mother_part", 0.95, (640, 500), 520, 60, 0.0)]
    for k, p in enumerate(recipe.placements):
        out.append(OBBDetection(f"b{k}", p.bolt, 0.9, (100 + k * 300, 80), 40, 40, 0.0))
        out.append(OBBDetection(f"p{k}", p.part, 0.9, (250 + k * 300, 80), 250 if p.part == "part_2hole" else 390, 90, 0.0))
    return tuple(out)


def judge(config, recipe, dets):
    svc = InspectionService(config, recipe)
    state = {"fid": 0, "ts": 0}

    def feed(d, ms):
        snap = None
        for _ in range(max(2, ms // 100)):
            state["fid"] += 1; state["ts"] += 100
            snap = svc.update(DetectionFrame(state["fid"], state["ts"], d))
        return snap

    feed(scattered(recipe), 1400)
    feed((OBBDetection("m", "mother_part", 0.95, (640, 500), 520, 60, 0.0),), 600)
    snap = feed(dets, 800)
    issues = [f"{i.code}" + (f":H{i.hole_id}" if i.hole_id else "") for i in snap.candidate.issues]
    return snap.status.value, issues


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("data", help="aabb 폴더")
    ap.add_argument("--refine", action="store_true", help="OpenCV 각도 보정")
    ap.add_argument("--max-angle", type=float, default=None, help="config 의 max_mother_angle_deg 를 덮어씀")
    ap.add_argument("--draw", default=None, help="보정된 박스·ROI 를 그린 그림을 저장할 폴더")
    a = ap.parse_args(argv)
    import cv2
    data = Path(a.data)
    config = load_config(ROOT / "config/mvp.json")
    if a.max_angle is not None:
        config["max_mother_angle_deg"] = a.max_angle
    recipes = {r: load_recipe(ROOT / f"config/recipes/{r}.json") for r in PHOTO_RECIPE.values()}
    if a.refine:
        from src.vision.angle_refiner import refine_detections
    if a.draw:
        from src.geometry.mother_frame import mother_pose
        from src.geometry.roi_builder import build_geometry
        from src.geometry.spatial import rectangle
        import numpy as np
        Path(a.draw).mkdir(parents=True, exist_ok=True)

    txts = sorted(p for p in (data / "labels").rglob("model_*.txt"))
    if not txts:
        sys.exit(f"{data}/labels 아래에 model_*.txt 가 없습니다")
    counts = collections.Counter(); bad = []; wrong_pass = 0
    for txt in txts:
        name = txt.stem; cls = name[:7]
        img = cv2.imread(str(data / "images" / txt.parent.name / (name + ".png")))
        if img is None:
            continue
        h, w = img.shape[:2]
        dets = label_detections(txt, w, h)
        if a.refine:
            dets = refine_detections(img, dets)
        mine = PHOTO_RECIPE[cls]
        status, issues = judge(config, recipes[mine], dets)
        others = {r: judge(config, recipes[r], dets)[0] for r in recipes if r != mine}
        counts[(cls, status)] += 1
        wrong_pass += sum(v == "PASS" for v in others.values())
        if status != "PASS":
            m = next(d for d in dets if d.class_name == "mother_part")
            bad.append((name, round(math.degrees(m.angle_rad), 1), status, issues[:2]))
        if a.draw:
            vis = img.copy()
            for d in dets:
                col = (0, 255, 0) if d.class_name == "mother_part" else (0, 200, 255) if d.class_name.startswith("part_") else (255, 200, 0)
                cv2.polylines(vis, [np.array(rectangle(d.center_xy, d.width, d.height, d.angle_rad), np.int32)], True, col, 2)
            try:
                geo = build_geometry(mother_pose(next(d for d in dets if d.class_name == "mother_part"), config), config)
                for hole, p in geo["holes"].items():
                    cv2.circle(vis, (int(p[0]), int(p[1])), 6, (255, 0, 255), -1)
                    cv2.putText(vis, f"H{hole}", (int(p[0]) - 10, int(p[1]) + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
            except ValueError:
                pass
            cv2.putText(vis, f"{name}  {status}  {' '.join(issues[:2])}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 255, 0) if status == "PASS" else (0, 0, 255), 2)
            cv2.imwrite(str(Path(a.draw) / f"{name}.jpg"), vis)

    total = sum(counts.values())
    passed = sum(v for (c, s), v in counts.items() if s == "PASS")
    print(f"사진 {total}장  ({'각도 보정' if a.refine else 'AABB 그대로'}, Mother 각도 제한 {config['max_mother_angle_deg']}°)")
    for cls in sorted({c for c, _ in counts}):
        row = {s: v for (c, s), v in counts.items() if c == cls}
        print(f"  {cls}: " + "  ".join(f"{s} {v}" for s, v in sorted(row.items())))
    print(f"자기 레시피 PASS {passed}/{total}   다른 레시피로 PASS(오판) {wrong_pass}건")
    if bad:
        print("\nPASS 가 아닌 사진:")
        for name, ang, status, issues in bad:
            print(f"  {name:12} mother {ang:6.1f}°  {status:12} {issues}")
    return 0 if wrong_pass == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
