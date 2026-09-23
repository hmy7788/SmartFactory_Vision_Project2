"""Live full-flow inspection: materials -> Mother registration -> assembly check.

Run from the repository root:
  python -m scripts.live_inspection --recipe recipe_1 --source 2 --device 0
  python -m scripts.live_inspection --recipe recipe_2 --source clip.mp4

Keys: 1/2/3 = switch recipe (new product) | n = new product (same recipe)
      r = register the Mother again | s = snapshot | q/ESC = quit
Every status change is appended to outputs/live_inspection/events_<time>.jsonl.
"""
import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.app.messages import PHASES, STATUSES, message, name, severity
from src.contracts.inspection import Phase, Status
from src.process.recipe import load_recipe
from src.vision.detection_adapter import from_ultralytics
from scripts.live_registration import CLASS_COLORS, Painter, find_weights, open_source

ROOT = Path(__file__).resolve().parents[1]
STATUS_COLORS = {"PASS": (0, 200, 0), "NG": (0, 0, 255), "IN_PROGRESS": (0, 200, 255),
                 "READY": (0, 200, 0), "HOLD": (180, 180, 180)}
SEVERITY_COLORS = {"error": (0, 0, 255), "info": (0, 200, 255), "wait": (220, 220, 220)}


def hole_colors(snapshot, recipe):
    """Per-hole overlay colour from the current candidate."""
    required = {p.mother_hole for p in recipe.placements}
    colors = {h: ((0, 200, 0) if h in required else (150, 150, 150)) for h in range(1, 6)}
    for issue in snapshot.candidate.issues:
        if issue.hole_id:
            colors[issue.hole_id] = (0, 0, 255) if severity(issue) == "error" else (0, 200, 255)
    return colors


def draw(view, snapshot, recipe, detections, painter, fps):
    ambiguous = set(snapshot.geometry.get("ambiguous_detections", ()))
    for d in detections:
        box = cv2.boxPoints(((d.center_xy[0], d.center_xy[1]), (d.width, d.height), np.degrees(d.angle_rad)))
        color = (255, 0, 255) if d.detection_id in ambiguous else CLASS_COLORS.get(d.class_name, (200, 200, 200))
        cv2.polylines(view, [box.astype(np.int32)], True, color, 4 if d.detection_id in ambiguous else 2)
        if d.detection_id in ambiguous:      # fits no Hole: magenta box with '?'
            cv2.putText(view, "?", (int(d.center_xy[0])-10, int(d.center_xy[1])+12),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 0, 255), 4)
    reg = snapshot.registration
    if snapshot.phase == Phase.REGISTER_MOTHER:
        for h in reg.get("holes_seen", []):
            color = (0, 200, 0) if h["visible"] else (0, 0, 255)
            cv2.circle(view, (int(h["xy"][0]), int(h["xy"][1])), 16, color, 2)
        bar = int(400*reg.get("progress", 0))
        cv2.rectangle(view, (16, view.shape[0]-40), (416, view.shape[0]-16), (80, 80, 80), 2)
        cv2.rectangle(view, (16, view.shape[0]-40), (16+bar, view.shape[0]-16), (0, 200, 0), -1)
    if snapshot.phase == Phase.ASSEMBLING and reg.get("holes"):
        colors = hole_colors(snapshot, recipe)
        for hole, (x, y) in reg["holes"].items():
            hole = int(hole)
            cv2.circle(view, (int(x), int(y)), 22, colors[hole], 3)
            label = f"H{hole}" + ("*" if hole in snapshot.occluded else "")
            cv2.putText(view, label, (int(x)-16, int(y)+48), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colors[hole], 2)

    target = " / ".join(f"H{p.mother_hole}: {name(p.bolt)} + {name(p.part)}" for p in recipe.placements)
    lines = [(f"{recipe.recipe_id}  |  {PHASES[snapshot.phase.value]}", (255, 255, 255)),
             (f"레시피: {target}", (200, 200, 200)),
             (f"상태: {STATUSES[snapshot.status.value]}" + ("" if snapshot.stable else "  (확인 중)"),
              STATUS_COLORS[snapshot.status.value])]
    issues = sorted(snapshot.candidate.issues, key=lambda i: ("error", "info", "wait").index(severity(i)))
    for issue in issues[:6]:
        lines.append(("• " + message(issue), SEVERITY_COLORS[severity(issue)]))
    if snapshot.occluded:
        lines.append((f"가려진 구멍(직전 상태 유지): {', '.join('H'+str(h) for h in snapshot.occluded)}", (255, 200, 0)))
    lines.append((f"FPS {fps:4.1f}   [1/2/3] 레시피  [n] 새 제품  [r] 재등록  [q] 종료", (160, 160, 160)))
    return painter.text(view, lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recipe", default="recipe_1", choices=["recipe_1", "recipe_2", "recipe_3"])
    parser.add_argument("--source", default="0", help="webcam index, video file or image")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=ROOT/"config/mvp.json")
    parser.add_argument("--device", default="cpu", help="'cpu' or GPU index like 0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--max-frame-gap-ms", type=float, default=None,
                        help="override config max_frame_gap_ms (slow CPU inference)")
    args = parser.parse_args()

    from ultralytics import YOLO
    weights = args.weights or find_weights()
    if not Path(weights).exists():
        raise SystemExit(f"가중치 없음: {weights}  (--weights 로 지정)")
    config = load_config(args.config)
    if args.max_frame_gap_ms:
        config["max_frame_gap_ms"] = args.max_frame_gap_ms
    mapping_path = ROOT/"config/class_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    model = YOLO(str(weights))
    recipe = load_recipe(ROOT/f"config/recipes/{args.recipe}.json")
    service = InspectionService(config, recipe)
    cap, still = open_source(args.source)
    if cap is not None and not cap.isOpened():
        raise SystemExit(f"영상 소스를 열 수 없음: {args.source}")
    painter = Painter()
    out_dir = ROOT/"outputs/live_inspection"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir/f"events_{datetime.now():%Y%m%d_%H%M%S}.jsonl").open("w", encoding="utf-8")
    print("weights:", weights, "| events:", log.name)
    start, frame_id, fps, slow_warned = time.monotonic(), 0, 0.0, False

    try:
        while True:
            tick = time.monotonic()
            if still is not None:
                image = still.copy()
            else:
                ok, image = cap.read()
                if not ok:
                    break
            timestamp_ms = (tick-start)*1000
            result = model.predict(image, conf=0.25, imgsz=args.imgsz, device=args.device, verbose=False)[0]
            frame = from_ultralytics(result, frame_id, timestamp_ms, mapping)
            snapshot = service.update(frame, image)
            for event in snapshot.events:
                log.write(json.dumps(event, ensure_ascii=False, default=str)+"\n")
                log.flush()
                print(f"[{timestamp_ms/1000:6.1f}s] {event.get('event_type')} {event.get('phase')} "
                      f"{event.get('status', '')}")
            detections = [d for d in frame.detections if d.confidence >= config["confidence_threshold"]]
            fps = 0.9*fps + 0.1/max(time.monotonic()-tick, 1e-6)
            if not slow_warned and frame_id > 30 and 1000/max(fps, 1e-6) > config["max_frame_gap_ms"]:
                print(f"경고: 프레임 간격 {1000/fps:.0f}ms > max_frame_gap_ms {config['max_frame_gap_ms']}ms. "
                      f"--device 0 (GPU) 또는 --max-frame-gap-ms 500 을 사용하세요.")
                slow_warned = True
            view = draw(image.copy(), snapshot, service.recipe, detections, painter, fps)
            cv2.imshow("Assembly inspection", view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("1"), ord("2"), ord("3")):
                service.reset(load_recipe(ROOT/f"config/recipes/recipe_{chr(key)}.json"))
                print("recipe ->", service.recipe.recipe_id)
            elif key == ord("n"):
                service.reset()
                print("new product")
            elif key == ord("r"):
                service.reregister()
                print("register Mother again")
            elif key == ord("s"):
                path = out_dir/f"snap_{frame_id:05d}.png"
                cv2.imwrite(str(path), view)
                print("saved", path)
            frame_id += 1
    finally:
        log.close()
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
