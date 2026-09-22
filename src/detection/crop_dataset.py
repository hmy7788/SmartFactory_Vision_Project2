"""
crop_dataset.py

⚠️ 이 스크립트로 만든 결과(data/iconic_cropped/)가 이후 data/iconic/으로 승격되었고
   원본 1280x720 raw 사진은 삭제되었다 (docs/cropped-dataset.md 참고).
   즉 지금 data/iconic/은 이미 720x720이라, 이 스크립트를 지금 그대로 재실행하면
   해상도 체크(ORIG_W,ORIG_H=1280,720)에 안 맞아 전부 걸러진다.
   다시 크롭이 필요하면(예: 새로 1280x720으로 재촬영한 경우) --input 인자로
   그 원본이 있는 폴더를 따로 가리켜야 한다 (data/iconic이 아닌 곳에 둘 것).

data/iconic/ (원본 1280x720, 검은 배경)를 720x720 정사각형으로 만든 뒤,
data/iconic_cropped/ 에 별도로 저장한다. 원본(data/iconic/)은 건드리지 않는다.
(위 경고 참고 — 이 문서 자체는 처음 만들 때 기준 설명이다.)

⚠️ 고정된 위치([280,1000))로 자르지 않는다 — 그러면 부품이 원본 왼쪽/오른쪽 끝에
   있는 사진(ICONIC 좌/우 위치 촬영분)은 통째로 잘려나간다.
   대신 **사진마다 부품 위치를 보고 크롭 윈도우를 그때그때 옮긴다**:
   1. 기존 OBB 라벨(data/labels/iconic/*.txt)에서 그 사진의 부품 중 가장 큰 박스를
      "메인 부품"으로 보고, 그 중심 x좌표를 구한다 (멀티박스 노이즈 파일 대비 —
      작은 노이즈 조각이 메인으로 잘못 선택되지 않도록 면적이 가장 큰 것을 고름).
   2. 그 중심이 크롭 윈도우(720폭)의 가운데에 오도록 좌표를 잡는다.
   3. 크롭 윈도우가 원본(1280폭) 밖으로 나가면, 나가지 않는 선에서 최대한 그 방향
      끝에 붙인다(clamp) — 사용자 요청대로 "잘리는 애들은 가운데로 넣고 크롭".
   → 부품이 하나뿐인 사진은 사실상 손실 없이 크롭된다.

라벨이 없는(빈) 파일은 기본값(원본 가운데, [280,1000))으로 크롭한다.

크롭 후 좌표계가 바뀌므로, 기존 OBB 라벨을 그대로 쓸 수 없다. 라벨은 이 스크립트가
만들지 않는다 — 크롭 후 auto_label_iconic.py를 다시 돌려서 새로 생성해야 한다
(사용법 참고).

사용법:
    python src/detection/crop_dataset.py --input <1280x720 원본 폴더> --labels <그 라벨 폴더> --output data/iconic_cropped
    python src/detection/auto_label_iconic.py --input data/iconic_cropped --output data/labels/iconic_cropped --preview data/preview/iconic_cropped
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # auto_label_iconic.py와 같은 폴더(src/detection/)
from auto_label_iconic import imread_unicode, imwrite_unicode, CLASS_TO_ID, IMG_EXTS  # noqa: E402

ORIG_W, ORIG_H = 1280, 720
CROP_SIZE = 720
DEFAULT_CROP_LEFT = (ORIG_W - CROP_SIZE) // 2  # 라벨 없을 때 쓰는 기본값(가운데), = 280


def main_box_center_x(label_path: Path):
    """
    라벨 파일에서 가장 큰(면적) 박스의 중심 x좌표(픽셀)를 반환.
    라벨이 없거나 비어있으면 None.
    """
    if not label_path.exists():
        return None
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    best_area = -1
    best_center_x = None
    for line in text.splitlines():
        coords = list(map(float, line.split()[1:]))
        xs_px = [c * ORIG_W for c in coords[0::2]]
        ys_px = [c * ORIG_H for c in coords[1::2]]
        x_min, x_max = min(xs_px), max(xs_px)
        y_min, y_max = min(ys_px), max(ys_px)
        area = (x_max - x_min) * (y_max - y_min)
        if area > best_area:
            best_area = area
            best_center_x = (x_min + x_max) / 2
    return best_center_x


def compute_crop_left(center_x):
    """중심 x가 크롭 윈도우 가운데 오도록 crop_left를 구하고, 프레임 밖이면 가장자리에 clamp."""
    if center_x is None:
        return DEFAULT_CROP_LEFT
    crop_left = round(center_x - CROP_SIZE / 2)
    return max(0, min(crop_left, ORIG_W - CROP_SIZE))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="ICONIC 원본(1280x720)을 720x720으로 동적 크롭")
    parser.add_argument("--input", default="data/iconic", help="1280x720 원본 이미지가 있는 폴더")
    parser.add_argument("--labels", default="data/labels/iconic",
                         help="--input에 대응하는 기존 OBB 라벨 폴더 (부품 중심 계산용)")
    parser.add_argument("--output", default="data/iconic_cropped", help="크롭 결과를 저장할 폴더")
    args = parser.parse_args()

    iconic_dir = Path(args.input)
    labels_dir = Path(args.labels)
    output_dir = Path(args.output)

    total_copied = 0
    crop_offsets = {}  # 파일별로 실제 어떤 crop_left를 썼는지 기록 (docs/검증용)
    used_default = 0

    for class_dir in sorted(iconic_dir.iterdir()):
        if not class_dir.is_dir() or class_dir.name not in CLASS_TO_ID:
            continue

        dst_dir = output_dir / class_dir.name
        dst_dir.mkdir(parents=True, exist_ok=True)

        class_copied = 0
        for img_path in sorted(class_dir.iterdir()):
            if img_path.suffix.lower() not in IMG_EXTS:
                continue

            image = imread_unicode(img_path)
            if image is None:
                print(f"[경고] 이미지를 읽을 수 없음: {img_path}", flush=True)
                continue

            h, w = image.shape[:2]
            if (w, h) != (ORIG_W, ORIG_H):
                print(f"[경고] 예상 해상도({ORIG_W}x{ORIG_H})와 다름({w}x{h}), 건너뜀: {img_path}", flush=True)
                continue

            label_path = labels_dir / f"{img_path.stem}.txt"
            center_x = main_box_center_x(label_path)
            if center_x is None:
                used_default += 1
            crop_left = compute_crop_left(center_x)
            crop_offsets[img_path.stem] = crop_left

            cropped = image[:, crop_left:crop_left + CROP_SIZE]
            imwrite_unicode(dst_dir / img_path.name, cropped)
            class_copied += 1
            total_copied += 1

        print(f"[{class_dir.name}] {class_copied}장 크롭 완료", flush=True)

    report_path = output_dir / "crop_offsets.json"
    report_path.write_text(
        json.dumps(crop_offsets, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n총 {total_copied}장 크롭 완료 (부품 중심 기준 동적 크롭)", flush=True)
    print(f"라벨 없어서 기본 위치(가운데) 사용: {used_default}장", flush=True)
    print(f"저장 위치: {output_dir}", flush=True)
    print(f"크롭 offset 기록: {report_path}", flush=True)
    print("\n다음 단계: auto_label_iconic.py로 새 라벨 생성 필요", flush=True)


if __name__ == "__main__":
    main()
