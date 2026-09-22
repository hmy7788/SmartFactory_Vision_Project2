"""
prepare_rtdetr_dataset.py

RT-DETR 실험용 데이터셋 준비 스크립트 (experiment/rt-detr 브랜치 전용).

RT-DETR(ultralytics)는 OBB(회전 박스)를 지원하지 않고 AABB(직사각형)만 받는다.

이 스크립트는 두 가지 소스를 합쳐서 하나의 학습셋을 만든다:
  1. data/iconic/  — 부품 1개짜리 ICONIC 사진. 라벨이 OBB(class x1 y1 x2 y2 x3 y3 x4 y4)
     포맷이라 각 라벨의 4개 꼭짓점에서 min/max를 취해 AABB(class xc yc w h)로 변환한다.
     ⚠️ 이 변환은 회전된 부품의 경우 AABB가 실제 부품보다 헐겁게(배경 포함) 잡힌다.
  2. data/assembled_labeled/  — 조립체(여러 부품이 한 프레임에) 사진. 라벨이 이미
     AABB 포맷이라 변환 없이 그대로 가져온다.
   (둘 다 동일한 클래스 ID 체계를 쓴다: bolt_2=0, bolt_1=1, mother_part=2,
    part_3hole=3, part_2hole=4)

출력 구조 (ultralytics detect 표준, 두 소스가 같은 images/labels 아래 섞여 들어감):
    datasets/rtdetr_combined/
    ├── images/{train,val}/...
    ├── labels/{train,val}/...   (AABB)
    └── data.yaml

Train/Val 분할: CLAUDE.md 방침(Val 없이 Train/Test)에 따라 별도 curated val 셋은 아니고,
ultralytics 학습 파이프라인이 요구하는 val 경로를 채우기 위해 각 소스마다 15%를
무작위로 떼어 val로 쓴다 (== 이 프로젝트에서 말하는 "Test"에 해당).

사용법:
    python src/detection/rt-detr/prepare_rtdetr_dataset.py \
        --iconic-images data/iconic \
        --iconic-labels data/labels/iconic \
        --assembled-images data/assembled_labeled/images \
        --assembled-labels data/assembled_labeled/labels \
        --output datasets/rtdetr_combined \
        --val-ratio 0.15 \
        --seed 42

    iconic만 쓰려면 --assembled-images/--assembled-labels를 생략하면 된다.
"""

import argparse
import random
import shutil
import sys
from pathlib import Path

CLASS_NAMES = ["bolt_2", "bolt_1", "mother_part", "part_3hole", "part_2hole"]
# 한글 ↔ 영문 코드 매핑: 볼트_주황=bolt_2, 볼트_노랑=bolt_1, 나무_5구멍=mother_part,
#                      나무_3구멍=part_3hole, 나무_2구멍=part_2hole
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def obb_line_to_aabb_line(line: str) -> str:
    """'class x1 y1 x2 y2 x3 y3 x4 y4' (0~1 정규화) → 'class xc yc w h' (0~1 정규화)."""
    parts = line.strip().split()
    class_id = parts[0]
    coords = list(map(float, parts[1:]))
    xs = coords[0::2]
    ys = coords[1::2]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    xc = (x_min + x_max) / 2
    yc = (y_min + y_max) / 2
    w = x_max - x_min
    h = y_max - y_min
    # 0~1 범위를 벗어나지 않도록 clip (경계 근처 부품 대비)
    xc, yc = min(max(xc, 0.0), 1.0), min(max(yc, 0.0), 1.0)
    w, h = min(max(w, 0.0), 1.0), min(max(h, 0.0), 1.0)
    return f"{class_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"


def convert_label_file(src_path: Path) -> list:
    lines = src_path.read_text(encoding="utf-8").strip().splitlines()
    return [obb_line_to_aabb_line(l) for l in lines if l.strip()]


def _split_and_copy(img_paths, label_lookup, output, val_ratio, convert_fn, source_name):
    """
    img_paths를 train/val로 나눠서 output/images,labels 아래로 복사.
    convert_fn(label_path) -> AABB 라인 리스트 (OBB면 변환, 이미 AABB면 그대로 읽기만).
    Returns: (train_count, val_count, skipped_no_label)
    """
    img_paths = sorted(img_paths)
    random.shuffle(img_paths)
    n_val = max(1, round(len(img_paths) * val_ratio)) if img_paths else 0
    val_set = set(img_paths[:n_val])

    train_count = val_count = skipped = 0
    for img_path in img_paths:
        label_path = label_lookup(img_path)
        if label_path is None or not label_path.exists():
            skipped += 1
            continue

        aabb_lines = convert_fn(label_path)
        split = "val" if img_path in val_set else "train"

        dst_img = output / "images" / split / img_path.name
        dst_label = output / "labels" / split / f"{img_path.stem}.txt"
        shutil.copy2(img_path, dst_img)
        dst_label.write_text("\n".join(aabb_lines), encoding="utf-8")

        if split == "train":
            train_count += 1
        else:
            val_count += 1

    print(f"[{source_name}] train {train_count} / val {val_count}"
          + (f" (라벨 없어서 {skipped}장 건너뜀)" if skipped else ""), flush=True)
    return train_count, val_count, skipped


def read_aabb_lines(label_path: Path) -> list:
    """이미 AABB 포맷인 라벨을 그대로 읽기 (data/assembled_labeled용)."""
    return [l for l in label_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


def build_dataset(iconic_images: Path, iconic_labels: Path,
                   assembled_images: Path, assembled_labels: Path,
                   output: Path, val_ratio: float, seed: int):
    random.seed(seed)

    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)

    total_train = 0
    total_val = 0
    skipped_no_label = 0

    # ── 1. data/iconic (OBB -> AABB 변환) ──────────────────────────
    for class_dir in sorted(iconic_images.iterdir()):
        if not class_dir.is_dir() or class_dir.name not in CLASS_NAMES:
            continue
        img_paths = [p for p in class_dir.iterdir() if p.suffix.lower() in IMG_EXTS]
        t, v, s = _split_and_copy(
            img_paths,
            lambda p: iconic_labels / f"{p.stem}.txt",
            output, val_ratio, convert_label_file, f"iconic/{class_dir.name}",
        )
        total_train += t
        total_val += v
        skipped_no_label += s

    # ── 2. data/assembled_labeled (이미 AABB) ──────────────────────
    # 파일명이 model_a_001.png 처럼 모델별 접두사로 되어 있으면, 전체를 한 덩어리로
    # 섞지 않고 모델(A/B/C)별로 따로 15%씩 떼어 val로 보낸다 (클래스/구성 비율 유지).
    if assembled_images and assembled_images.is_dir():
        all_paths = [p for p in assembled_images.iterdir() if p.suffix.lower() in IMG_EXTS]
        groups = {}
        for p in all_paths:
            parts = p.stem.split("_")
            group = "_".join(parts[:2]) if len(parts) >= 2 and parts[0] == "model" else "assembled_labeled"
            groups.setdefault(group, []).append(p)

        for group_name, paths in sorted(groups.items()):
            t, v, s = _split_and_copy(
                paths,
                lambda p: assembled_labels / f"{p.stem}.txt",
                output, val_ratio, read_aabb_lines, f"assembled_labeled/{group_name}",
            )
            total_train += t
            total_val += v
            skipped_no_label += s

    data_yaml = output / "data.yaml"
    yaml_lines = [
        f"path: {output.resolve().as_posix()}",
        "train: images/train",
        "val: images/val",
        f"nc: {len(CLASS_NAMES)}",
        "names:",
    ]
    for i, name in enumerate(CLASS_NAMES):
        yaml_lines.append(f"  {i}: {name}")
    data_yaml.write_text("\n".join(yaml_lines), encoding="utf-8")

    print(f"\n[완료] train: {total_train}장, val: {total_val}장", flush=True)
    if skipped_no_label:
        print(f"[경고] 라벨 없어서 건너뜀: {skipped_no_label}장", flush=True)
    print(f"data.yaml 저장: {data_yaml}", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="iconic(OBB)+assembled_labeled(AABB) -> RT-DETR용 통합 데이터셋")
    parser.add_argument("--iconic-images", default="data/iconic")
    parser.add_argument("--iconic-labels", default="data/labels/iconic")
    parser.add_argument("--assembled-images", default="data/assembled_labeled/images",
                         help="빈 문자열로 주면 assembled_labeled 없이 iconic만 사용")
    parser.add_argument("--assembled-labels", default="data/assembled_labeled/labels")
    parser.add_argument("--output", default="datasets/rtdetr_combined")
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_dataset(
        Path(args.iconic_images), Path(args.iconic_labels),
        Path(args.assembled_images) if args.assembled_images else None,
        Path(args.assembled_labels) if args.assembled_labels else None,
        Path(args.output), args.val_ratio, args.seed,
    )


if __name__ == "__main__":
    main()
