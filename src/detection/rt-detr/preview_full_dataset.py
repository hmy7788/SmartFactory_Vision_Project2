"""
preview_full_dataset.py

datasets/rtdetr_full의 각 그룹(iconic/assembled_labeled/labeled_data의 picking·process)에서
샘플 몇 장을 뽑아 라벨(AABB, canonical 클래스명)을 그려서 data/preview/rtdetr_full에 저장한다.
"""
import sys
from pathlib import Path
import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "detection"))
from auto_label_iconic import imread_unicode, imwrite_unicode  # noqa: E402

DATASET = REPO_ROOT / "datasets" / "rtdetr_full"
OUT = REPO_ROOT / "data" / "preview" / "rtdetr_full"

CLASS_NAMES = ["bolt_2", "bolt_1", "mother_part", "part_3hole", "part_2hole"]
COLORS = [(0, 165, 255), (0, 255, 255), (255, 0, 0), (255, 0, 255), (0, 255, 0)]


def group_of(stem: str) -> str:
    if stem.startswith("recipe1"):
        return "process_model_a"
    if stem.startswith("recipe2"):
        return "process_model_b"
    if stem.startswith("recipe3"):
        return "process_model_c"
    if stem.startswith("2_hole"):
        return "picking_part_2hole"
    if stem.startswith("3_hole"):
        return "picking_part_3hole"
    if stem.startswith("5_hole"):
        return "picking_mother_part"
    if stem.startswith("b_frame"):
        return "picking_bolt_1"
    if stem.startswith("model_a"):
        return "assembled_model_a"
    if stem.startswith("model_b"):
        return "assembled_model_b"
    if stem.startswith("model_c"):
        return "assembled_model_c"
    for name in CLASS_NAMES:
        if stem.startswith(name):
            return f"iconic_{name}"
    return "other"


def draw(img_path: Path, label_path: Path, out_path: Path):
    image = imread_unicode(img_path)
    if image is None:
        print(f"[warn] cannot read {img_path}")
        return
    h, w = image.shape[:2]
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            cls_id = int(parts[0])
            xc, yc, bw, bh = map(float, parts[1:5])
            x1 = int((xc - bw / 2) * w); y1 = int((yc - bh / 2) * h)
            x2 = int((xc + bw / 2) * w); y2 = int((yc + bh / 2) * h)
            color = COLORS[cls_id]
            name = CLASS_NAMES[cls_id]
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.putText(image, name, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    imwrite_unicode(out_path, image)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    groups = {}
    for split in ("train", "val"):
        img_dir = DATASET / "images" / split
        label_dir = DATASET / "labels" / split
        for img_path in sorted(img_dir.iterdir()):
            g = group_of(img_path.stem)
            groups.setdefault(g, []).append((img_path, label_dir / f"{img_path.stem}.txt"))

    for g, items in sorted(groups.items()):
        step = max(1, len(items) // 2)
        picked = items[::step][:2]
        for img_path, label_path in picked:
            out_path = OUT / f"{g}__{img_path.name}"
            draw(img_path, label_path, out_path)
        print(f"[{g}] {len(items)}장 중 {len(picked)}장 미리보기 저장", flush=True)

    print(f"\n저장 위치: {OUT}", flush=True)


if __name__ == "__main__":
    main()
