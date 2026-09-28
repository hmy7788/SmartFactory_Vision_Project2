"""Model-driven development overlay. Never changes inspection angle limits."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from math import degrees

from src.app.config import load_config
from src.contracts.detections import OBBDetection
from src.geometry.mother_frame import mother_pose, major_axis
from src.geometry.roi_builder import build_geometry
from src.geometry.spatial import rectangle

ROOT = Path(__file__).resolve().parents[1]


def draw_overlay(source, records, geometry, message, part_type, destination):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default(size=18)
    for record in records:
        d = record
        poly = rectangle(d["center_xy"], d["width"], d["height"], d["angle_rad"])
        draw.line(list(poly)+[poly[0]], fill="#aaaaaa", width=2)
        draw.text(poly[0], f'{d["class_name"]} {d["confidence"]:.2f}', font=font, fill="white", stroke_width=1, stroke_fill="black")
    if geometry:
        p = geometry["pose"]
        poly = rectangle(p["center"], p["width"], p["height"], p["angle_rad"])
        draw.line(list(poly)+[poly[0]], fill="#38ff79", width=3)
        for hole, rois in geometry["part_rois"].items():
            poly = rois[part_type]
            draw.line(list(poly)+[poly[0]], fill="#44cfff" if part_type == "part_2hole" else "#ef83ff", width=3)
        for hole, poly in geometry["bolt_rois"].items():
            draw.line(list(poly)+[poly[0]], fill="#ffca28", width=3)
            x,y = geometry["holes"][hole]
            draw.ellipse((x-5,y-5,x+5,y+5),fill="#ff4433")
            draw.text((x-12,y+12),f"H{hole}",font=font,fill="white",stroke_width=2,stroke_fill="black")
    # Separate header prevents annotations from obscuring image coordinates.
    canvas = Image.new("RGB", (image.width, image.height+100), "#121923")
    canvas.paste(image,(0,100))
    header = ImageDraw.Draw(canvas)
    header.text((15,10),message,font=font,fill="white")
    header.text((15,38),f"Green: Mother | Yellow: Bolt ROI | Cyan/Pink: {part_type} ROI | Red: Hole",font=font,fill="white")
    header.text((15,66),"UNVALIDATED ROI SETTINGS - diagnostic overlay only",font=font,fill="#ffca28")
    canvas.save(destination)


def main():
    from ultralytics import YOLO
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT/"model/yolo_obb_parts.pt")
    parser.add_argument("--class-mapping", type=Path, default=ROOT/"config/class_mapping.json")
    parser.add_argument("--images", type=Path, default=ROOT/"sample_img")
    parser.add_argument("--config", type=Path, default=ROOT/"config/mvp.json")
    parser.add_argument("--output", type=Path, default=ROOT/"outputs/roi_debug")
    parser.add_argument("--conf", type=float, default=.25, help="Diagnostic inference threshold; does not change MVP threshold")
    parser.add_argument("--preview-outside-angle", action="store_true", help="Show rejected pose geometry for debugging only")
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error("Local model file does not exist")
    config = load_config(args.config)
    mapping = json.loads(args.class_mapping.read_text(encoding="utf-8"))
    model = YOLO(str(args.model))
    names = {i: mapping.get(name,name) for i,name in model.names.items()}
    report = {"model": str(args.model), "task": model.task, "names": model.names, "config": config,
              "inference_confidence": args.conf, "class_mapping": mapping, "normalized_names": names, "images": []}
    print("MODEL CLASSES:",model.names)
    output = args.output/datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True,exist_ok=False)
    files = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {".jpg",".jpeg",".png"})
    if not files:
        parser.error("No sample images found")
    for path in files:
        result = model.predict(str(path),conf=args.conf,device="cpu",verbose=False,save=False)[0]
        records = []
        if result.obb is not None:
            for i,(box,cls,confidence) in enumerate(zip(result.obb.xywhr.cpu().tolist(),result.obb.cls.cpu().tolist(),result.obb.conf.cpu().tolist())):
                records.append(dict(detection_id=str(i),class_name=names[int(cls)],confidence=confidence,
                                    center_xy=box[:2],width=box[2],height=box[3],angle_rad=box[4]))
        mothers = [d for d in records if d["class_name"] == "mother_part" and d["confidence"] >= config["confidence_threshold"]]
        geometry = None
        message = "HOLD: MOTHER_NOT_FOUND"
        if "mother_part" not in names.values():
            message = "MODEL_CLASS_MISMATCH: no mother_part class - no inferred ROIs"
        elif len(mothers)>1:
            message = "HOLD: MULTIPLE_MOTHERS"
        elif len(mothers)==1:
            detection = OBBDetection(**mothers[0])
            try:
                pose = mother_pose(detection,config)
                message = f"Mother detected | angle={degrees(pose['angle_rad']):.1f} deg"
                geometry = build_geometry(pose,config)
            except ValueError:
                message = f"HOLD: MOTHER_ANGLE_OUT_OF_RANGE ({degrees(major_axis(detection)[2]):.1f} deg)"
                if args.preview_outside_angle:
                    preview = {**config,"max_mother_angle_deg":90}
                    geometry = build_geometry(mother_pose(detection,preview),config)
                    message += " | PREVIEW ONLY"
        entry = {"image":str(path),"status":message,"detections":records,"geometry":geometry}
        report["images"].append(entry)
        for part in ("part_2hole","part_3hole"):
            draw_overlay(path,records,geometry,message,part,output/f"{path.stem}_{part}.png")
        print(path.name, message, f"({len(records)} detections)")
    (output/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print("OUTPUT:",output)


if __name__ == "__main__":
    main()
