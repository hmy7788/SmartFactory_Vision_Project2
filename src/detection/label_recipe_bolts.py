"""
label_recipe_bolts.py

완성된 조립체 사진(예: data/recipe_1/)에서 볼트(bolt_1=노랑, bolt_2=주황)만
색상(HSV) 기준으로 자동 라벨링한다.

⚠️ 왜 auto_label_iconic.py를 못 쓰는가:
   조립체 사진은 나무 막대 2개가 물리적으로 맞닿아 있고 볼트도 나무 구멍에 파묻혀 있어서,
   밝기 기준 윤곽선(findContours)으로는 전부 하나의 덩어리로 합쳐진다 (실제 확인함).
   나무 막대끼리는 색도 같아서 구분할 방법이 없다 — 그래서 나무 막대는 이 스크립트로
   라벨링하지 않는다(범위 밖). 볼트는 색이 뚜렷해서 HSV 마스킹으로 나무와 분리 가능하다.

HSV 기준값은 기존 라벨링된 data/iconic/bolt_1, bolt_2 샘플에서 직접 뽑아 보정한 값:
    bolt_1(노랑): H 23~29
    bolt_2(주황): H 12~18
   (겹치는 구간 없이 깔끔히 분리됨. S>100, V>80으로 어두운/무채색 영역 제외)

사용법:
    python src/detection/label_recipe_bolts.py --input data/recipe_1 --output data/labels/recipe_1 --preview data/preview/recipe_1
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_label_iconic import imread_unicode, imwrite_unicode, IMG_EXTS  # noqa: E402

# CLAUDE.md/auto_label_iconic.py와 동일한 클래스 ID 매핑
CLASS_TO_ID = {
    "bolt_2": 0,  # 주황
    "bolt_1": 1,  # 노랑
}

# data/iconic/bolt_1, bolt_2 샘플에서 실측한 HSV 범위 (밝기 보정 후 기준).
HSV_RANGES = {
    "bolt_2": ((10, 100, 60), (20, 255, 255)),   # 주황
    "bolt_1": ((21, 100, 60), (31, 255, 255)),   # 노랑
}

TARGET_BRIGHTNESS = 60  # 이 평균 밝기에 맞춰 어두운 사진을 밝게 보정
MAX_GAIN = 4.0


def normalize_brightness(image):
    """
    조립체 사진 중 조명이 어두운 것들에서 HSV 채도(S)가 불안정해져(어두운 픽셀은
    실제로는 무채색인데도 S가 높게 나옴) 나무까지 볼트 색으로 오탐되는 문제가 있었다.
    평균 밝기가 낮은 이미지는 TARGET_BRIGHTNESS에 맞춰 선형으로 밝혀서 이 문제를 줄인다.
    (과증폭으로 노이즈가 커지는 걸 막기 위해 MAX_GAIN으로 상한을 둠)
    """
    gray_mean = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean()
    gain = min(TARGET_BRIGHTNESS / max(gray_mean, 1.0), MAX_GAIN)
    if gain <= 1.0:
        return image
    return cv2.convertScaleAbs(image, alpha=gain, beta=0)

MIN_AREA_RATIO = 0.0005  # 이보다 작은 컨투어는 노이즈로 간주


def find_bolt_obboxes(image):
    """
    HSV 색상 마스킹으로 bolt_1(노랑)/bolt_2(주황) 컨투어를 각각 찾아 OBB로 반환.
    Returns: list of (class_name, points(4,2) float32)
    """
    bright_image = normalize_brightness(image)
    hsv = cv2.cvtColor(bright_image, cv2.COLOR_BGR2HSV)
    h_img, w_img = image.shape[:2]
    min_area = MIN_AREA_RATIO * w_img * h_img

    results = []
    for cls, (lo, hi) in HSV_RANGES.items():
        mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            rect = cv2.minAreaRect(cnt)
            (rw, rh) = rect[1]
            box_area = rw * rh
            # 실제 볼트는 사각/육각형에 가까워 컨투어 면적이 박스 면적을 꽤 채운다.
            # 나무결 노이즈 등 가늘고 불규칙한 모양은 이 비율(solidity)이 낮아 걸러짐.
            if box_area <= 0 or area / box_area < 0.5:
                continue
            points = cv2.boxPoints(rect)
            results.append((cls, points))

    return results


def to_yolo_obb_format(points, img_w, img_h):
    coords = []
    for x, y in points:
        coords.append(x / img_w)
        coords.append(y / img_h)
    return coords


def process_dataset(input_dir, output_dir, preview_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    preview_dir = Path(preview_dir) if preview_dir else None

    output_dir.mkdir(parents=True, exist_ok=True)
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)

    total_images = 0
    total_boxes = 0
    zero_box_images = []

    img_files = sorted(f for f in input_dir.iterdir() if f.suffix.lower() in IMG_EXTS)
    for img_path in img_files:
        image = imread_unicode(img_path)
        if image is None:
            print(f"[경고] 이미지를 읽을 수 없음: {img_path}", flush=True)
            continue

        img_h, img_w = image.shape[:2]
        detections = find_bolt_obboxes(image)
        total_images += 1

        if not detections:
            zero_box_images.append(str(img_path))

        lines = []
        for cls, points in detections:
            class_id = CLASS_TO_ID[cls]
            coords = to_yolo_obb_format(points, img_w, img_h)
            coords_str = " ".join(f"{v:.6f}" for v in coords)
            lines.append(f"{class_id} {coords_str}")
            total_boxes += 1

        label_path = output_dir / f"{img_path.stem}.txt"
        label_path.write_text("\n".join(lines), encoding="utf-8")

        if preview_dir:
            preview_img = image.copy()
            for cls, points in detections:
                color = (0, 165, 255) if cls == "bolt_2" else (0, 255, 255)  # BGR: 주황/노랑
                pts_int = points.astype(np.int32)
                cv2.polylines(preview_img, [pts_int], True, color, 2)
                top_pt = points[points[:, 1].argmin()]
                cv2.putText(preview_img, cls, (int(top_pt[0]), max(0, int(top_pt[1]) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            imwrite_unicode(preview_dir / img_path.name, preview_img)

    # classes.txt (bolt_1/bolt_2만 — 이 스크립트는 볼트 전용)
    (output_dir / "classes.txt").write_text(
        "\n".join(name for name, _ in sorted(CLASS_TO_ID.items(), key=lambda kv: kv[1])),
        encoding="utf-8",
    )

    print(f"\n총 처리 이미지: {total_images}장", flush=True)
    print(f"총 생성 박스(bolt만): {total_boxes}개", flush=True)
    if zero_box_images:
        print(f"\n⚠️ 볼트가 하나도 검출되지 않은 이미지 {len(zero_box_images)}장 (수동 확인 필요):", flush=True)
        for p in zero_box_images:
            print(f"  - {p}", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="조립체 사진에서 볼트만 색상 기준 자동 라벨링")
    parser.add_argument("--input", required=True, help="조립체 사진 폴더 (예: data/recipe_1)")
    parser.add_argument("--output", required=True, help="라벨(.txt) 저장 폴더")
    parser.add_argument("--preview", default=None, help="미리보기 이미지 저장 폴더")
    args = parser.parse_args()

    process_dataset(args.input, args.output, args.preview)


if __name__ == "__main__":
    main()
