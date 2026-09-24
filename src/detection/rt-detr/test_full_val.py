"""
test_full_val.py

RT-DETR 학습된 가중치로 test 셋 전체를 추론해서, 박스+클래스+confidence가
그려진 이미지를 저장한다 (experiment/rt-detr 브랜치 전용).

3차 실험(iconic+assembled_labeled+labeled_data_merged, 980장 전체 병합)부터는
data/aabb/images/test(149장)를 대상으로 한다.

사용법:
    python src/detection/rt-detr/test_full_val.py
    python src/detection/rt-detr/test_full_val.py --weights runs/rtdetr/full_run/weights/best.pt
"""

import argparse
import sys
from pathlib import Path

import cv2
from ultralytics import RTDETR

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="RT-DETR test셋 전체 추론 테스트")
    parser.add_argument("--images", default=str(REPO_ROOT / "data" / "aabb" / "images" / "test"))
    parser.add_argument("--weights", default=str(REPO_ROOT / "runs" / "rtdetr" / "full_run" / "weights" / "last.pt"))
    parser.add_argument("--output", default=str(REPO_ROOT / "runs" / "rtdetr_test" / "full_run"))
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()

    images_dir = Path(args.images)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    img_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
    print(f"[TEST] 대상 이미지: {len(img_paths)}장 ({images_dir})", flush=True)
    print(f"[TEST] 가중치: {args.weights}", flush=True)

    model = RTDETR(args.weights)

    no_detection = []
    total_boxes = 0
    for i, img_path in enumerate(img_paths, 1):
        image = cv2.imread(str(img_path))
        if image is None:
            print(f"[경고] 이미지를 읽을 수 없음: {img_path}", flush=True)
            continue

        results = model.predict(image, conf=args.conf, verbose=False)
        n_boxes = len(results[0].boxes)
        total_boxes += n_boxes
        if n_boxes == 0:
            no_detection.append(img_path.name)

        annotated = results[0].plot().copy()
        cv2.imwrite(str(output_dir / img_path.name), annotated)
        print(f"[{i}/{len(img_paths)}] {img_path.name} -> box {n_boxes}개", flush=True)

    print(f"\n[완료] 총 {len(img_paths)}장, 검출 박스 합계 {total_boxes}개", flush=True)
    if no_detection:
        print(f"[경고] 박스 0개로 검출된 이미지 {len(no_detection)}장:", flush=True)
        for name in no_detection:
            print(f"  - {name}", flush=True)
    print(f"결과 저장 위치: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
