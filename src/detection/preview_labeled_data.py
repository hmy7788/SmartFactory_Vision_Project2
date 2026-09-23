"""
preview_labeled_data.py (임시 검토용 — data/labeled_data 리뷰 전용)

data/labeled_data/{subfolder}에서 샘플 이미지 몇 장에 라벨(AABB, Darknet 포맷)을 그려서
미리보기로 저장한다. _darknet.labels가 있으면 그 클래스명을 쓰고, 없으면 class id 숫자만 표시.
"""
import sys
from pathlib import Path
import cv2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "detection"))
from auto_label_iconic import imread_unicode, imwrite_unicode  # noqa: E402

ROOT = REPO_ROOT / "data" / "labeled_data"
OUT = REPO_ROOT / "runs" / "labeled_data_preview"
COLORS = [(0,165,255),(0,255,255),(255,0,0),(0,255,0),(255,0,255),(255,255,0)]

def draw(folder, n=6):
    fdir = ROOT / folder
    labels_file = fdir / "_darknet.labels"
    class_names = labels_file.read_text(encoding="utf-8").strip().splitlines() if labels_file.exists() else None

    imgs = sorted([p for p in fdir.iterdir() if p.suffix.lower() in (".jpg", ".png")])
    out_dir = OUT / folder
    out_dir.mkdir(parents=True, exist_ok=True)

    step = max(1, len(imgs) // n)
    picked = imgs[::step][:n]

    for img_path in picked:
        image = imread_unicode(img_path)
        if image is None:
            print(f"[warn] cannot read {img_path}")
            continue
        h, w = image.shape[:2]
        label_path = fdir / f"{img_path.stem}.txt"
        if label_path.exists():
            for line in label_path.read_text(encoding="utf-8").strip().splitlines():
                parts = line.split()
                cls_id = int(parts[0])
                xc, yc, bw, bh = map(float, parts[1:5])
                x1 = int((xc - bw/2) * w); y1 = int((yc - bh/2) * h)
                x2 = int((xc + bw/2) * w); y2 = int((yc + bh/2) * h)
                color = COLORS[cls_id % len(COLORS)]
                name = class_names[cls_id] if class_names and cls_id < len(class_names) else str(cls_id)
                cv2.rectangle(image, (x1,y1), (x2,y2), color, 2)
                cv2.putText(image, name, (x1, max(0,y1-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        imwrite_unicode(out_dir / img_path.name, image)
    print(f"[{folder}] {len(picked)}장 미리보기 저장 -> {out_dir}")

for folder in ["2_hole_label", "3_hole_label", "b1_label", "train", "train2", "train3"]:
    draw(folder)
