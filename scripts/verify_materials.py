"""Inspect independent material photos against all recipes; no temporal claims."""
import json
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
from PIL import Image, ImageOps, ImageDraw, ImageFont
from ultralytics import YOLO
from src.app.config import load_config
from src.process.recipe import load_recipe
from src.process.materials import evaluate_materials
from src.vision.detection_adapter import from_ultralytics
from src.geometry.spatial import rectangle

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",choices=["recipe_1","recipe_2","recipe_3","all"],default="recipe_1")
    args = parser.parse_args()
    config = load_config(ROOT/"config/mvp.json")
    mapping = json.loads((ROOT/"config/class_mapping.json").read_text(encoding="utf-8"))
    model = YOLO(str(ROOT/"model/yolo_obb_parts.pt"))
    names = [f"recipe_{i}" for i in (1,2,3)] if args.recipe == "all" else [args.recipe]
    recipes = [load_recipe(ROOT/f"config/recipes/{name}.json") for name in names]
    output = ROOT/"outputs/material_debug"/datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True)
    report = {"model":str(ROOT/"model/yolo_obb_parts.pt"),"confidence_threshold":config["confidence_threshold"],
              "note":"Independent still images; READY is a candidate, not a confirmed transition.","cases":[]}
    for path in sorted((ROOT/"sample_img").glob("material_sample_*.jpg")):
        source = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        result = model.predict(source,conf=.25,imgsz=640,device="cpu",verbose=False)[0]
        frame = from_ultralytics(result,0,0,mapping)
        accepted = tuple(d for d in frame.detections if d.confidence>=config["confidence_threshold"])
        case = {"image":str(path),"detections": [asdict(d) for d in frame.detections],"recipes":{}}
        lines = [path.name+" | MATERIAL CHECK (still-image candidate)"]
        for recipe in recipes:
            candidate,counts = evaluate_materials(recipe,accepted)
            case["recipes"][recipe.recipe_id] = {"candidate":asdict(candidate),"counts":counts}
            lines.append(f"{recipe.recipe_id}: {candidate.status.value}")
            lines.extend(f"  {i.code}: expected {i.expected}, observed {i.observed}" for i in candidate.issues)
        print(path.name,json.dumps(case["recipes"],ensure_ascii=False))
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf",20)
        except OSError:
            font = ImageFont.load_default(size=20)
        scale = min(1,1200/source.width)
        photo = source.resize((round(source.width*scale),round(source.height*scale)))
        draw = ImageDraw.Draw(photo)
        for d in frame.detections:
            points = [(x*scale,y*scale) for x,y in rectangle(d.center_xy,d.width,d.height,d.angle_rad)]
            color = "#43ff87" if d.confidence>=config["confidence_threshold"] else "#aaaaaa"
            draw.line(points+[points[0]],fill=color,width=3)
            draw.text(points[0],f"{d.class_name} {d.confidence:.3f}",font=font,fill=color,stroke_width=2,stroke_fill="black")
        header = len(lines)*26+20
        canvas = Image.new("RGB",(max(1200,photo.width),photo.height+header),"#15202b")
        canvas.paste(photo,(0,header))
        drawer = ImageDraw.Draw(canvas)
        for i,line in enumerate(lines):
            drawer.text((12,10+i*26),line,font=font,fill="white")
        canvas.save(output/f"{path.stem}.png")
        report["cases"].append(case)
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("OUTPUT:",output)


if __name__ == "__main__":
    main()
