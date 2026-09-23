"""Mother registration check on still images (repeated as a 1.2 s static clip).

Run from the repository root:
  python -m scripts.check_registration                       # sample_img/mother_sample_*.jpg
  python -m scripts.check_registration --images path/to/dir  # any folder/file
Writes overlay PNGs to outputs/registration_debug/<timestamp>/.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import cv2

from src.app.config import load_config
from src.geometry.mother_registration import MotherRegistrar
from src.vision.detection_adapter import from_ultralytics
from src.vision.hole_detector import measure_holes

ROOT = Path(__file__).resolve().parents[1]


def images(path):
    path = Path(path)
    if path.is_file():
        return [path]
    return sorted(p for p in path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"})


def draw(image, frame, mothers, measurements, status, config):
    for d in frame.detections:
        if d.class_name != "mother_part":
            continue
        m = measurements.get(d.detection_id)
        for h in (m.holes if m else ()):
            color = (0, 200, 0) if h.visible else (0, 0, 255)
            cv2.circle(image, (int(h.x), int(h.y)), 18, color, 2)
            cv2.putText(image, f"H{h.hole_id} {h.contrast:.2f}", (int(h.x)-30, int(h.y)-26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    if status.locked:
        for hole, (x, y) in status.lock.geometry(config)["holes"].items():
            cv2.drawMarker(image, (int(x), int(y)), (255, 255, 0), cv2.MARKER_CROSS, 22, 2)
        text = "REGISTERED"
    else:
        text = "REJECTED: " + ", ".join(i.code + (f"({i.observed})" if i.observed else "") for i in status.issues)
    cv2.putText(image, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 4)
    cv2.putText(image, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0) if status.locked else (0, 0, 255), 2)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", type=Path, default=None)
    parser.add_argument("--images", type=Path, default=ROOT/"sample_img")
    parser.add_argument("--pattern", default="mother_sample_*", help="glob used when --images is sample_img")
    parser.add_argument("--config", type=Path, default=ROOT/"config/mvp.json")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    from ultralytics import YOLO
    config = load_config(args.config)
    mapping_path = ROOT/"config/class_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    from scripts.live_registration import find_weights
    weights = args.weights or find_weights()
    print("weights:", weights)
    model = YOLO(str(weights))
    paths = sorted(args.images.glob(args.pattern+".*")) if args.images == ROOT/"sample_img" else images(args.images)
    output = ROOT/"outputs/registration_debug"/datetime.now().strftime("%Y%m%d_%H%M%S")
    output.mkdir(parents=True)
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        result = model.predict(image, conf=0.25, imgsz=640, device=args.device, verbose=False)[0]
        frame = from_ultralytics(result, 0, 0, mapping)
        detections = [d for d in frame.detections if d.confidence >= config["confidence_threshold"]]
        mothers = [d for d in detections if d.class_name == "mother_part"]
        components = [d for d in detections if d.class_name != "mother_part"]
        measurements = {d.detection_id: measure_holes(image, d, config) for d in mothers}
        registrar = MotherRegistrar(config)
        for t in range(0, 1300, 100):                 # static image = hands-off clip
            status = registrar.update(t, mothers, components, measurements)
        cv2.imwrite(str(output/f"{path.stem}.png"), draw(image.copy(), frame, mothers, measurements, status, config))
        if status.locked:
            print(f"{path.name}: REGISTERED holes(alpha,beta)="
                  f"{[(round(a, 3), round(b, 3)) for a, b in status.lock.hole_local]}")
        else:
            print(f"{path.name}: REJECTED {[(i.code, i.observed) for i in status.issues]}")
    print("OUTPUT:", output)


if __name__ == "__main__":
    main()
