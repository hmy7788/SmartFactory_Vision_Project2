"""
preview_dataset.py

{dataset}/의 images+labels 전체(train/test 등 images/ 아래 존재하는 모든 split)에 박스를
그려서 {output}에 저장한다. AABB(class xc yc w h)와 OBB(class x1 y1 x2 y2 x3 y3 x4 y4)
라벨 포맷을 모두 지원한다 (한 줄의 숫자 개수로 자동 판별: 4개면 AABB, 8개면 OBB).

사용법:
    python src/detection/preview_dataset.py --dataset data/aabb --output data/preview/aabb
    python src/detection/preview_dataset.py --dataset data/obb --output data/preview/obb
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "detection"))
from auto_label_iconic import imread_unicode, imwrite_unicode  # noqa: E402

CLASS_NAMES = ["bolt_2", "bolt_1", "mother_part", "part_3hole", "part_2hole"]
COLORS = [(0, 165, 255), (0, 255, 255), (255, 0, 0), (255, 0, 255), (0, 255, 0)]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def draw_boxes(image, label_path: Path):
    if not label_path.exists():
        return image
    h, w = image.shape[:2]
    for line in label_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        cls_id = int(parts[0])
        nums = list(map(float, parts[1:]))
        color = COLORS[cls_id]
        name = CLASS_NAMES[cls_id]

        if len(nums) == 4:  # AABB: xc yc w h
            xc, yc, bw, bh = nums
            x1, y1 = int((xc - bw / 2) * w), int((yc - bh / 2) * h)
            x2, y2 = int((xc + bw / 2) * w), int((yc + bh / 2) * h)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            top_pt = (x1, max(0, y1 - 8))
        else:  # OBB: x1 y1 x2 y2 x3 y3 x4 y4
            pts = [(int(nums[i] * w), int(nums[i + 1] * h)) for i in range(0, 8, 2)]
            pts_np = np.array(pts, dtype=np.int32)
            cv2.polylines(image, [pts_np], True, color, 2)
            top_idx = min(range(4), key=lambda i: pts[i][1])
            top_pt = (pts[top_idx][0], max(0, pts[top_idx][1] - 8))

        cv2.putText(image, name, top_pt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return image


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="데이터셋 전체 이미지에 라벨(AABB/OBB 자동판별) 그려서 미리보기 저장")
    parser.add_argument("--dataset", required=True, help="datasets/rtdetr_full 처럼 images/labels가 있는 폴더")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    dataset = Path(args.dataset)
    output = Path(args.output)

    total = 0
    for split_dir in sorted((dataset / "images").iterdir()):
        if not split_dir.is_dir():
            continue
        split = split_dir.name
        img_dir = dataset / "images" / split
        label_dir = dataset / "labels" / split
        if not img_dir.is_dir():
            continue
        out_split_dir = output / split
        out_split_dir.mkdir(parents=True, exist_ok=True)

        img_paths = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
        for i, img_path in enumerate(img_paths, 1):
            image = imread_unicode(img_path)
            if image is None:
                print(f"[경고] 읽기 실패: {img_path}", flush=True)
                continue
            label_path = label_dir / f"{img_path.stem}.txt"
            draw_boxes(image, label_path)
            imwrite_unicode(out_split_dir / img_path.name, image)
            total += 1
            if i % 100 == 0:
                print(f"[{split}] {i}/{len(img_paths)}장 처리", flush=True)

        print(f"[{split}] 완료: {len(img_paths)}장 -> {out_split_dir}", flush=True)

    print(f"\n총 {total}장 저장 완료 -> {output}", flush=True)


if __name__ == "__main__":
    main()
