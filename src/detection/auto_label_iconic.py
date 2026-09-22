"""
auto_label_iconic.py

ICONIC 데이터셋(검은 배경, TOP-DOWN, 정적 촬영) 자동 OBB(Oriented Bounding Box) 라벨링 스크립트.

전제 조건:
- 배경이 검은색(또는 어두운 단색)이고 부품이 배경보다 밝은 색일 것
- 이미지 폴더 구조: data/iconic/{class_name}/*.jpg (또는 .png)
  예) data/iconic/bolt_2/*.jpg, data/iconic/mother_part/*.jpg ...

클래스명(한글 ↔ 영문 코드) 매핑:
  나무_5구멍 = mother_part / 볼트_노랑 = bolt_1 / 볼트_주황 = bolt_2
  나무_2구멍 = part_2hole  / 나무_3구멍 = part_3hole
  (폴더명은 영문 코드 사용 — 한글 경로 이슈 회피 목적)

⚠️ 이 스크립트는 ICONIC(검은 배경, 손 없음) 데이터 전용입니다.
   손이 포함된 픽킹 영상 프레임에는 사용하지 마세요 (occlusion 때문에 부정확해짐 — Roboflow 권장).

⚠️ 라벨 형식은 AABB(직사각형)가 아니라 OBB(회전된 사각형)이다.
   나무 막대/볼트가 여러 각도(0°/45°/90°/135°)로 놓인 채 촬영되므로,
   회전 없는 직사각형은 배경을 많이 포함해 박스가 헐겁다.
   cv2.minAreaRect로 부품에 딱 맞는 회전 사각형을 구해서 저장한다.
   → YOLO 학습 시 detect가 아니라 **obb task**(예: yolov8n-obb, yolo11n-obb)를 써야 한다.

사용법:
    python src/detection/auto_label_iconic.py --input data/iconic --output data/labels/iconic --preview data/preview/iconic

출력:
- YOLO-OBB 포맷 라벨 (.txt): 클래스ID x1 y1 x2 y2 x3 y3 x4 y4 (4개 꼭짓점, 전부 0~1 정규화)
- 미리보기 이미지: 회전된 박스를 그려서 저장 (자동 라벨링 결과를 눈으로 확인하기 위한 용도 — 반드시 몇 장은 확인해볼 것)
- classes.txt: YOLO 학습에 쓰이는 클래스 목록 파일
"""

import argparse
import sys
import cv2
import numpy as np
from pathlib import Path

# ── 클래스 이름 → ID 매핑 (폴더명이 다르면 여기를 수정) ──
CLASS_TO_ID = {
    "bolt_2": 0,        # 볼트_주황
    "bolt_1": 1,         # 볼트_노랑
    "mother_part": 2,     # 나무_5구멍
    "part_3hole": 3,      # 나무_3구멍
    "part_2hole": 4,       # 나무_2구멍
}

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def imread_unicode(path):
    """
    cv2.imread는 Windows에서 한글(비ASCII) 경로를 못 읽는다.
    클래스 폴더명이 전부 한글(볼트_주황 등)이므로 이 프로젝트에서는 필수.
    np.fromfile + cv2.imdecode로 우회.
    """
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except (FileNotFoundError, ValueError):
        return None


def imwrite_unicode(path, image):
    """cv2.imwrite의 한글 경로 우회 버전 (imread_unicode와 짝)."""
    path = Path(path)
    ext = path.suffix if path.suffix else ".jpg"
    ok, buf = cv2.imencode(ext, image)
    if ok:
        buf.tofile(str(path))
    return ok


def find_part_obboxes(image, min_area_ratio=0.001, thresh_value=None):
    """
    검은 배경 위 밝은 부품의 회전된 바운딩 박스(OBB)를 전부 찾아서 반환.
    "여러 개 동시 배치" 사진처럼 부품이 여러 개 있어도 서로 떨어져 있으면 각각 별도 박스로 검출됨.

    주의: 부품끼리 서로 맞닿아 있으면 하나의 컨투어로 합쳐져 박스가 1개만 나올 수 있음
          (이 경우는 자동화 한계 — 미리보기 이미지로 확인 후 수동 보정 필요).

    Returns: list of (4, 2) float32 ndarray — cv2.boxPoints() 순서 그대로의 꼭짓점 4개 (픽셀 좌표)
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h_img, w_img = gray.shape

    # Otsu 자동 threshold (조명 변화에 어느 정도 강건함). 필요시 --thresh로 고정값 지정 가능.
    if thresh_value is None:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(gray, thresh_value, 255, cv2.THRESH_BINARY)

    # 작은 노이즈(그림자, 천 주름, 반사광 등) 제거
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # RETR_EXTERNAL: 바깥 윤곽선만 사용 (나무 부품의 구멍은 내부 컨투어라 자동 무시됨 — 원하는 동작)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = min_area_ratio * w_img * h_img
    obboxes = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue  # 노이즈로 판단하고 제외
        rect = cv2.minAreaRect(cnt)  # (center(x,y), (w,h), angle)
        points = cv2.boxPoints(rect)  # (4, 2) — 부품에 딱 맞는 회전 사각형 꼭짓점
        obboxes.append(points)

    return obboxes


def to_yolo_obb_format(points, img_w, img_h):
    """
    (4, 2) 픽셀 좌표 꼭짓점 → YOLO-OBB 포맷(x1 y1 x2 y2 x3 y3 x4 y4, 0~1 정규화) flat list.
    """
    normalized = []
    for x, y in points:
        normalized.append(x / img_w)
        normalized.append(y / img_h)
    return normalized


def process_dataset(input_dir, output_dir, preview_dir, min_area_ratio, thresh_value):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    preview_dir = Path(preview_dir) if preview_dir else None

    output_dir.mkdir(parents=True, exist_ok=True)
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)

    total_images = 0
    total_boxes = 0
    zero_box_images = []
    multi_box_images = []  # "여러 개 동시 배치" 사진 등, 박스가 2개 이상 나온 경우 — 검수 시 참고용

    for class_dir in sorted(input_dir.iterdir()):
        if not class_dir.is_dir():
            continue
        class_name = class_dir.name
        if class_name not in CLASS_TO_ID:
            print(f"[경고] '{class_name}' 폴더는 CLASS_TO_ID에 정의되지 않아 건너뜀")
            continue
        class_id = CLASS_TO_ID[class_name]

        for img_path in sorted(class_dir.iterdir()):
            if img_path.suffix.lower() not in IMG_EXTS:
                continue

            image = imread_unicode(img_path)
            if image is None:
                print(f"[경고] 이미지를 읽을 수 없음: {img_path}")
                continue

            img_h, img_w = image.shape[:2]
            obboxes = find_part_obboxes(image, min_area_ratio=min_area_ratio, thresh_value=thresh_value)
            total_images += 1

            if not obboxes:
                zero_box_images.append(str(img_path))
            elif len(obboxes) > 1:
                multi_box_images.append(str(img_path))

            # YOLO-OBB 라벨 파일 저장 (이미지와 같은 이름의 .txt)
            label_path = output_dir / f"{img_path.stem}.txt"
            lines = []
            for points in obboxes:
                coords = to_yolo_obb_format(points, img_w, img_h)
                coords_str = " ".join(f"{v:.6f}" for v in coords)
                lines.append(f"{class_id} {coords_str}")
                total_boxes += 1
            label_path.write_text("\n".join(lines), encoding="utf-8")

            # 미리보기 이미지 저장 (회전 박스를 그려서 눈으로 확인용)
            if preview_dir:
                preview_img = image.copy()
                for points in obboxes:
                    pts_int = points.astype(np.int32)
                    cv2.polylines(preview_img, [pts_int], isClosed=True, color=(0, 255, 0), thickness=2)
                    top_pt = points[points[:, 1].argmin()]
                    cv2.putText(preview_img, class_name,
                                (int(top_pt[0]), max(0, int(top_pt[1]) - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                imwrite_unicode(preview_dir / img_path.name, preview_img)

    # classes.txt 생성 (YOLO 학습 시 필요)
    classes_path = output_dir / "classes.txt"
    sorted_classes = sorted(CLASS_TO_ID.items(), key=lambda kv: kv[1])
    classes_path.write_text("\n".join(name for name, _ in sorted_classes), encoding="utf-8")

    print(f"\n총 처리 이미지: {total_images}장")
    print(f"총 생성 박스(OBB): {total_boxes}개")
    print(f"classes.txt 저장: {classes_path}")

    if zero_box_images:
        print(f"\n⚠️ 박스가 하나도 검출되지 않은 이미지 {len(zero_box_images)}장 (반드시 수동 확인 필요):")
        for p in zero_box_images[:20]:
            print(f"  - {p}")
        if len(zero_box_images) > 20:
            print(f"  ... 외 {len(zero_box_images) - 20}장 더")

    if multi_box_images:
        print(f"\nℹ️ 박스가 2개 이상 검출된 이미지 {len(multi_box_images)}장 "
              f"('여러 개 동시 배치' 사진일 수도, 노이즈 오검출일 수도 있음 — 미리보기로 확인 권장):")
        for p in multi_box_images[:10]:
            print(f"  - {p}")
        if len(multi_box_images) > 10:
            print(f"  ... 외 {len(multi_box_images) - 10}장 더")


def main():
    # Windows 콘솔(cp949)에서 ⚠️/ℹ️ 같은 이모지 출력 시 UnicodeEncodeError 방지
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="ICONIC 데이터셋 자동 OBB 라벨링")
    parser.add_argument("--input", required=True, help="data/iconic 같은 클래스별 폴더가 있는 루트 경로")
    parser.add_argument("--output", required=True, help="YOLO-OBB 라벨(.txt)을 저장할 경로")
    parser.add_argument("--preview", default=None, help="박스 그려진 미리보기 이미지를 저장할 경로 (선택, 강력 추천)")
    parser.add_argument("--min-area-ratio", type=float, default=0.001,
                         help="이미지 면적 대비 최소 컨투어 비율 (이보다 작으면 노이즈로 간주, 기본 0.001)")
    parser.add_argument("--thresh", type=int, default=None,
                         help="고정 threshold 값 (지정 안 하면 Otsu 자동 threshold 사용)")
    args = parser.parse_args()

    process_dataset(args.input, args.output, args.preview, args.min_area_ratio, args.thresh)


if __name__ == "__main__":
    main()
