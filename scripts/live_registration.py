"""Live Mother registration test (webcam / video / image).

Run from the repository root:
  python -m scripts.live_registration                    # webcam 0
  python -m scripts.live_registration --source 2         # webcam 2
  python -m scripts.live_registration --source clip.mp4  # video file
  python -m scripts.live_registration --device 0         # GPU

How to test
  1. Put only the Mother on the table, top face (5 holes) up, roughly horizontal.
  2. Take your hands off. After ~1 s the screen shows "등록 완료" and cyan H1~H5.
  3. Now cover it with your hand / put parts on it: the locked holes must stay.
  4. Slide the Mother and leave it: after ~1 s it re-locks at the new place.
Keys: r = register again, s = save snapshot, q/ESC = quit
"""
import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from src.app.config import load_config
from src.geometry.mother_registration import MotherRegistrar, MotherTracker
from src.vision.detection_adapter import from_ultralytics
from src.vision.hole_detector import measure_holes

ROOT = Path(__file__).resolve().parents[1]

MESSAGES = {
    "MOTHER_NOT_FOUND": "Mother가 보이지 않습니다",
    "MULTIPLE_MOTHERS": "Mother가 여러 개 보입니다. 하나만 두세요",
    "MOTHER_ANGLE_OUT_OF_RANGE": "Mother를 가로로 놓아주세요",
    "MOTHER_SHAPE_MISMATCH": "Mother가 아닌 부품입니다 (길이 비율 불일치)",
    "MOTHER_NOT_CLEAR": "Mother 위의 부품을 치워주세요",
    "MOTHER_HOLES_NOT_VISIBLE": "구멍 5개가 보이도록 윗면을 위로 놓아주세요",
    "MOTHER_HOLE_LAYOUT_MISMATCH": "구멍 배치가 Mother와 다릅니다",
    "HOLE_MEASUREMENT_UNAVAILABLE": "구멍 측정 불가",
    "MOTHER_REGISTERING": "손을 떼고 기다려주세요... 등록 중",
    "MOTHER_MOVING": "Mother 이동 감지 - 다시 고정 중",
    "MOTHER_LOST": "Mother가 오래 가려져 있습니다",
}
CLASS_COLORS = {"mother_part": (0, 200, 80), "bolt_1": (0, 230, 230), "bolt_2": (0, 140, 255),
                "part_2hole": (200, 80, 255), "part_3hole": (80, 180, 255)}


def find_weights():
    for base in (ROOT, *ROOT.parents[:2]):
        for name in ("checkpoints/yolo26_obb_parts.pt", "model/yolo_obb_parts.pt"):
            if (base/name).exists():
                return base/name
    return ROOT/"checkpoints/yolo26_obb_parts.pt"


class Painter:
    """Hangul text via Pillow (cv2.putText cannot draw Korean)."""

    def __init__(self):
        self.font = None
        try:
            from PIL import ImageFont
            for path in ("C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                         "/System/Library/Fonts/AppleSDGothicNeo.ttc"):
                try:
                    self.font = ImageFont.truetype(path, 26)
                    break
                except OSError:
                    continue
        except ImportError:
            pass

    def text(self, image, lines, origin=(16, 16)):
        if self.font is None:
            for i, (line, color) in enumerate(lines):
                cv2.putText(image, line.encode("ascii", "replace").decode(), (origin[0], origin[1]+28*(i+1)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            return image
        from PIL import Image, ImageDraw
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for i, (line, color) in enumerate(lines):
            draw.text((origin[0], origin[1]+34*i), line, font=self.font, fill=color[::-1],
                      stroke_width=3, stroke_fill=(0, 0, 0))
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def open_source(source):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(int(source))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return cap, None
    path = Path(source)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
        return None, cv2.imread(str(path))
    return cv2.VideoCapture(str(path)), None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="0", help="webcam index, video file or image")
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=ROOT/"config/mvp.json")
    parser.add_argument("--device", default="cpu", help="'cpu' or GPU index like 0")
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    from ultralytics import YOLO
    weights = args.weights or find_weights()
    if not Path(weights).exists():
        raise SystemExit(f"가중치 없음: {weights}  (--weights 로 지정)")
    print("weights:", weights)
    config = load_config(args.config)
    mapping_path = ROOT/"config/class_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    model = YOLO(str(weights))
    cap, still = open_source(args.source)
    if cap is not None and not cap.isOpened():
        raise SystemExit(f"영상 소스를 열 수 없음: {args.source}")
    painter = Painter()
    snapshots = ROOT/"outputs/live_registration"
    registrar, tracker = MotherRegistrar(config), None
    start, frame_id, fps = time.monotonic(), 0, 0.0

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
        detections = [d for d in frame.detections if d.confidence >= config["confidence_threshold"]]
        mothers = [d for d in detections if d.class_name == "mother_part"]
        components = [d for d in detections if d.class_name != "mother_part"]

        view = image.copy()
        for d in detections:
            box = cv2.boxPoints(((d.center_xy[0], d.center_xy[1]), (d.width, d.height), np.degrees(d.angle_rad)))
            cv2.polylines(view, [box.astype(np.int32)], True, CLASS_COLORS.get(d.class_name, (200, 200, 200)), 2)

        lines = []
        if tracker is None:
            measurements = {d.detection_id: measure_holes(image, d, config) for d in mothers}
            status = registrar.update(timestamp_ms, mothers, components, measurements)
            shown = measurements.get(status.mother_id) if status.mother_id else None
            for h in (shown.holes if shown else ()):
                color = (0, 200, 0) if h.visible else (0, 0, 255)
                cv2.circle(view, (int(h.x), int(h.y)), 16, color, 2)
            if status.locked:
                tracker = MotherTracker(status.lock, config)
                print(f"[{timestamp_ms/1000:6.1f}s] 등록 완료 holes={[(round(a, 3), round(b, 3)) for a, b in status.lock.hole_local]}")
            else:
                lines.append(("단계: Mother 등록", (255, 255, 255)))
                for issue in status.issues:
                    lines.append((MESSAGES.get(issue.code, issue.code), (0, 200, 255)))
                bar = int(400*status.progress)
                cv2.rectangle(view, (16, view.shape[0]-40), (416, view.shape[0]-16), (80, 80, 80), 2)
                cv2.rectangle(view, (16, view.shape[0]-40), (16+bar, view.shape[0]-16), (0, 200, 0), -1)
        if tracker is not None:
            lock, issues, events = tracker.update(timestamp_ms, mothers)
            for event in events:
                print(f"[{timestamp_ms/1000:6.1f}s] {event['event_type']}")
            lines.append(("등록 완료 - 조립 단계 (r: 다시 등록)", (0, 255, 0)))
            for issue in issues:
                lines.append((MESSAGES.get(issue.code, issue.code), (0, 0, 255)))
            for hole, (x, y) in lock.geometry(config)["holes"].items():
                cv2.circle(view, (int(x), int(y)), 20, (255, 255, 0), 2)
                cv2.putText(view, f"H{hole}", (int(x)-14, int(y)-26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        fps = 0.9*fps + 0.1/max(time.monotonic()-tick, 1e-6)
        lines.append((f"FPS {fps:4.1f}", (200, 200, 200)))
        view = painter.text(view, lines)
        cv2.imshow("Mother registration (q: quit, r: reset, s: save)", view)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            registrar, tracker = MotherRegistrar(config), None
            print("reset")
        if key == ord("s"):
            snapshots.mkdir(parents=True, exist_ok=True)
            path = snapshots/f"snap_{frame_id:05d}.png"
            cv2.imwrite(str(path), view)
            print("saved", path)
        frame_id += 1
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
