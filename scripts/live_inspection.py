"""Live full-flow inspection: materials -> Mother registration -> assembly -> final verdict.

Run from the repository root:
  python -m scripts.live_inspection --recipe recipe_1 --source 2 --device 0
  python -m scripts.live_inspection --recipe recipe_2 --source clip.mp4 --no-sound

Keys (click the video window first):
  Enter / c = assembly finished -> final verdict now
  r         = after a final NG: re-assemble | otherwise: register the Mother again
  1 / 2 / 3 = next product with recipe_1/2/3      n = next product, same recipe
  m = sound on/off   s = snapshot   q / ESC = quit
Outputs: outputs/live_inspection/events_<time>.jsonl, results_<time>.csv, snap_*.png
"""
import argparse
import csv
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from statistics import median

import cv2
import numpy as np

from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.app.messages import (PHASES, STATUSES, final_issue_message, final_message, message, name,
                              severity)
from src.app.sound import Sounder
from src.contracts.inspection import Phase, Status
from src.process.recipe import load_recipe
from src.vision.detection_adapter import from_ultralytics
from scripts.live_registration import CLASS_COLORS, Painter, find_weights, open_source

ROOT = Path(__file__).resolve().parents[1]
GREEN, RED, YELLOW, ORANGE, GRAY, WHITE = (0, 200, 0), (0, 0, 255), (0, 220, 255), (0, 140, 255), (160, 160, 160), (255, 255, 255)
STATUS_COLORS = {"PASS": GREEN, "NG": RED, "IN_PROGRESS": YELLOW, "READY": GREEN, "HOLD": GRAY}
ORDER = ("bolt_1", "bolt_2", "part_2hole", "part_3hole", "mother_part")

BANNERS = {   # event_type -> (text, colour, seconds, sound)
    "MATERIALS_READY": ("재료 확인 완료!  Mother만 가로로 놓고 손을 떼주세요", GREEN, 3.0, "step"),
    "ASSEMBLY_STARTED": ("Mother 등록 완료  —  조립을 시작하세요", GREEN, 3.0, "ok"),
    "MOTHER_RELOCKED": ("Mother 위치를 다시 맞췄습니다", YELLOW, 1.5, None),
    "REASSEMBLY_STARTED": ("재조립 시작  —  틀린 부분을 고쳐주세요", YELLOW, 2.5, None),
}


class Display:
    def __init__(self, painter, sounder):
        self.painter, self.sounder = painter, sounder
        self.banners = []                        # [(text, colour, until)]
        self.materials = deque(maxlen=10)        # smoothed checklist counts

    def notify(self, text, color, seconds):
        self.banners = [(text, color, time.monotonic()+seconds)]

    def on_events(self, events):
        for event in events:
            kind = event.get("event_type")
            if kind in BANNERS:
                text, color, seconds, sound = BANNERS[kind]
                self.notify(text, color, seconds)
                if sound:
                    self.sounder.play(sound)
            elif kind == "NG_ALERT":
                self.sounder.play("ng")
            elif kind == "PRODUCT_RESULT":
                self.sounder.play("pass" if event["result"]["result"] == "PASS" else "fail")

    # ---- per phase ------------------------------------------------------
    def _checklist(self, view, snapshot, y):
        if not snapshot.materials:
            return view
        self.materials.append(snapshot.materials["observed"])
        expected = snapshot.materials["expected"]
        entries = []
        for i, cls in enumerate(c for c in ORDER if expected.get(c) or any(m.get(c) for m in self.materials)):
            have = int(median(m.get(cls, 0) for m in self.materials))
            need = expected.get(cls, 0)
            mark, color = ("OK", GREEN) if have == need else (("부족", YELLOW) if have < need else ("초과", RED))
            entries.append((f"{name(cls):10s} {have}/{need}  {mark}", color, (24, y+40*i), 30))
        return self.painter.items(view, entries)

    def _hole_colors(self, snapshot, recipe):
        required = {p.mother_hole for p in recipe.placements}
        colors = {h: (GREEN if h in required else GRAY) for h in range(1, 6)}
        source = snapshot.confirmed or snapshot.candidate
        for issue in source.issues:
            if issue.hole_id:
                if severity(issue) == "error":
                    colors[issue.hole_id] = RED if snapshot.alert else ORANGE
                else:
                    colors[issue.hole_id] = YELLOW
        return colors

    def draw(self, view, snapshot, recipe, detections, fps):
        h, w = view.shape[:2]
        ambiguous = set(snapshot.geometry.get("ambiguous_detections", ()))
        for d in detections:
            box = cv2.boxPoints(((d.center_xy[0], d.center_xy[1]), (d.width, d.height), np.degrees(d.angle_rad)))
            color = (255, 0, 255) if d.detection_id in ambiguous else CLASS_COLORS.get(d.class_name, (200, 200, 200))
            cv2.polylines(view, [box.astype(np.int32)], True, color, 2)

        phase, reg, result = snapshot.phase, snapshot.registration, snapshot.result
        # Frame border: red only for a lasting confirmed NG (or final NG).
        if snapshot.alert or (phase == Phase.RESULT and result.get("result") == "NG"):
            cv2.rectangle(view, (0, 0), (w-1, h-1), RED, 28)
        elif phase == Phase.RESULT or (phase == Phase.ASSEMBLING and snapshot.status in (Status.IN_PROGRESS, Status.PASS)):
            cv2.rectangle(view, (0, 0), (w-1, h-1), GREEN, 10)
        elif phase == Phase.ASSEMBLING and snapshot.status == Status.NG:
            cv2.rectangle(view, (0, 0), (w-1, h-1), ORANGE, 10)       # NG not yet confirmed long enough

        target = " / ".join(f"H{p.mother_hole}: {name(p.bolt)}+{name(p.part)}" for p in recipe.placements)
        header = [(f"{recipe.recipe_id}  |  {PHASES[phase.value]}", WHITE),
                  (f"레시피  {target}", (220, 220, 220))]
        if phase in (Phase.ASSEMBLING, Phase.CHECK_MATERIALS):
            header.append((f"상태: {STATUSES[snapshot.status.value]}" + ("" if snapshot.stable else " (확인 중)"),
                           STATUS_COLORS[snapshot.status.value]))
        view = self.painter.text(view, header, origin=(24, 22), size=26)

        if phase != Phase.CHECK_MATERIALS:
            self.materials.clear()
        if phase == Phase.CHECK_MATERIALS:
            view = self._checklist(view, snapshot, 140)
            view = self.painter.banner(view, "레시피 재료를 모두 화면에 펼쳐주세요", WHITE, size=30, y_ratio=0.9)
        elif phase == Phase.REGISTER_MOTHER:
            for hole in reg.get("holes_seen", []):
                cv2.circle(view, (int(hole["xy"][0]), int(hole["xy"][1])), 16, GREEN if hole["visible"] else RED, 2)
            bar = int(420*reg.get("progress", 0))
            cv2.rectangle(view, (24, h-60), (444, h-30), (80, 80, 80), 2)
            cv2.rectangle(view, (24, h-60), (24+bar, h-30), GREEN, -1)
            issue = next(iter(snapshot.candidate.issues), None)
            view = self.painter.banner(view, message(issue) if issue else "Mother 등록 중", YELLOW, size=34, y_ratio=0.82)
        elif phase in (Phase.ASSEMBLING, Phase.RESULT) and reg.get("holes"):
            colors = self._hole_colors(snapshot, recipe)
            for hole, (x, y) in reg["holes"].items():
                hole = int(hole)
                cv2.circle(view, (int(x), int(y)), 24, colors[hole], 4)
                label = f"H{hole}" + ("*" if hole in snapshot.occluded else "")
                cv2.putText(view, label, (int(x)-18, int(y)+52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colors[hole], 2)

        if phase == Phase.ASSEMBLING:
            source = snapshot.confirmed or snapshot.candidate
            issues = sorted(set(source.issues) | {i for i in snapshot.candidate.issues if i.code == "AMBIGUOUS_ASSOCIATION"},
                            key=lambda i: ("error", "info", "wait").index(severity(i)))
            lines = []
            for issue in issues[:6]:
                sev = severity(issue)
                color = (RED if snapshot.alert else ORANGE) if sev == "error" else (YELLOW if sev == "info" else GRAY)
                lines.append(("• " + message(issue), color))
            if snapshot.occluded:
                lines.append((f"가려진 구멍(이전 상태 유지): {', '.join('H'+str(o) for o in snapshot.occluded)}", GRAY))
            view = self.painter.text(view, lines, origin=(24, 140), size=28)
            if snapshot.alert:
                first = next(i for i in issues if severity(i) == "error")
                view = self.painter.banner(view, "[오류] " + message(first), RED, size=46, y_ratio=0.8)
            elif snapshot.status == Status.PASS:
                view = self.painter.banner(view, "모두 맞습니다 — 확정 중...", GREEN, size=40, y_ratio=0.8)
        elif phase == Phase.RESULT:
            ok = result.get("result") == "PASS"
            view = self.painter.banner(view, final_message(result), GREEN if ok else RED, size=46, y_ratio=0.45)
            info = [(f"제품 #{result.get('product_seq')}  조립 시간 {result.get('assembly_ms', 0)/1000:.1f}초  "
                     f"({'자동' if result.get('decided_by') == 'auto' else '작업자 완료'})", WHITE)]
            if not ok:
                from src.contracts.inspection import Issue
                info += [("• " + final_issue_message(Issue(**i)), RED) for i in result.get("issues", [])[:5]]
            view = self.painter.text(view, info, origin=(24, 110), size=28)

        self.banners = [b for b in self.banners if b[2] > time.monotonic()]
        for text, color, _ in self.banners:
            view = self.painter.banner(view, text, color, size=44, y_ratio=0.5)
        keys = "[Enter] 조립 완료  [r] 재조립/재등록  [1/2/3] 다음 제품  [m] 소리  [q] 종료"
        return self.painter.text(view, [(f"FPS {fps:4.1f}   {keys}", (170, 170, 170))], origin=(24, h-26), size=18)


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
    parser.add_argument("--no-sound", action="store_true")
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
    service = InspectionService(config, load_recipe(ROOT/f"config/recipes/{args.recipe}.json"))
    cap, still = open_source(args.source)
    if cap is not None and not cap.isOpened():
        raise SystemExit(f"영상 소스를 열 수 없음: {args.source}")
    sounder = Sounder(enabled=not args.no_sound, sounds_dir=ROOT/"assets/sounds")
    display = Display(Painter(), sounder)
    out_dir = ROOT/"outputs/live_inspection"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    log = (out_dir/f"events_{stamp}.jsonl").open("w", encoding="utf-8")
    results_path = out_dir/f"results_{stamp}.csv"
    print("weights:", weights, "| events:", log.name, "| results:", results_path.name)
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
                print(f"[{timestamp_ms/1000:6.1f}s] {event.get('event_type')} {event.get('phase')} {event.get('status', '')}")
                if event.get("event_type") == "PRODUCT_RESULT":
                    r = event["result"]
                    new = not results_path.exists()
                    with results_path.open("a", newline="", encoding="utf-8-sig") as f:
                        writer = csv.writer(f)
                        if new:
                            writer.writerow(["time", "product_seq", "recipe_id", "result", "decided_by",
                                             "assembly_s", "final_issues", "ng_history"])
                        writer.writerow([datetime.now().isoformat(timespec="seconds"), r["product_seq"],
                                         r["recipe_id"], r["result"], r["decided_by"],
                                         None if r["assembly_ms"] is None else round(r["assembly_ms"]/1000, 1),
                                         ";".join(f"{i['code']}:H{i['hole_id']}" for i in r["issues"]),
                                         ";".join(r["issue_history"])])
            display.on_events(snapshot.events)
            if snapshot.alert:
                sounder.play("ng")                    # repeats every 2 s while the NG lasts
            detections = [d for d in frame.detections if d.confidence >= config["confidence_threshold"]]
            fps = 0.9*fps + 0.1/max(time.monotonic()-tick, 1e-6)
            if not slow_warned and frame_id > 30 and 1000/max(fps, 1e-6) > config["max_frame_gap_ms"]:
                print(f"경고: 프레임 간격 {1000/fps:.0f}ms > max_frame_gap_ms {config['max_frame_gap_ms']}ms. "
                      f"--device 0 (GPU) 또는 --max-frame-gap-ms 500 을 사용하세요.")
                slow_warned = True
            view = display.draw(image.copy(), snapshot, service.recipe, detections, fps)
            cv2.imshow("Assembly inspection", view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("1"), ord("2"), ord("3")):
                service.reset(load_recipe(ROOT/f"config/recipes/recipe_{chr(key)}.json"))
                display.notify(f"recipe_{chr(key)} 선택  —  재료를 화면에 펼쳐주세요", WHITE, 2.5)
            elif key == ord("n"):
                service.reset()
                display.notify(f"{service.recipe.recipe_id} 다음 제품  —  재료를 화면에 펼쳐주세요", WHITE, 2.5)
            elif key in (13, 10, ord("c")):
                if service.complete():
                    print("assembly finished by worker")
            elif key == ord("r"):
                if service.machine.phase == Phase.RESULT:
                    if service.result.get("result") == "NG":
                        service.reassemble()
                else:
                    service.reregister()
                    display.notify("Mother 재등록  —  Mother만 두고 손을 떼주세요", YELLOW, 2.5)
            elif key == ord("m"):
                sounder.enabled = not sounder.enabled
                display.notify("소리 켜짐" if sounder.enabled else "소리 꺼짐", WHITE, 1.2)
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
