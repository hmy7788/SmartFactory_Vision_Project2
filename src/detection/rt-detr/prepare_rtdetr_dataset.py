"""
prepare_rtdetr_dataset.py

RT-DETR 실험용 데이터셋 준비 스크립트 (experiment/rt-detr 브랜치 전용).

RT-DETR(ultralytics)는 OBB(회전 박스)를 지원하지 않고 AABB(직사각형)만 받는다.

이 스크립트는 세 가지 소스를 합쳐서 하나의 학습셋을 만든다:
  1. data/iconic/  — 부품 1개짜리 ICONIC 사진. 라벨이 OBB(class x1 y1 x2 y2 x3 y3 x4 y4)
     포맷이라 각 라벨의 4개 꼭짓점에서 min/max를 취해 AABB(class xc yc w h)로 변환한다.
     ⚠️ 이 변환은 회전된 부품의 경우 AABB가 실제 부품보다 헐겁게(배경 포함) 잡힌다.
  2. data/assembled_labeled/  — 완성된 조립체(Model A/B/C) 사진. 라벨이 이미
     AABB 포맷이라 변환 없이 그대로 가져온다.
  3. data/labeled_data_merged/  — 픽킹 영상(손 포함) + 조립 진행중 프레임, canonical
     클래스 ID로 이미 변환됨 (merge_labeled_data.py 결과물). 그대로 읽기만 한다.
   (셋 다 동일한 클래스 ID 체계를 쓴다: bolt_2=0, bolt_1=1, mother_part=2,
    part_3hole=3, part_2hole=4)

⚠️ 중복 제거: data/labeled_data_merged/의 일부 사진(구 data/labeled_data/train의 "C270 ..."
   100장)은 data/qwer → data/assembled_labeled로 이어진 것과 **완전히 동일한 원본**이다
   (md5 확인함, 파일명만 다름). 그대로 합치면 같은 사진이 다른 라벨로 두 번 들어간다.
   그래서 이 스크립트는 복사하기 전에 **파일 내용 md5 해시**로 이미 추가된 이미지인지
   검사해서, 중복이면 건너뛴다(먼저 처리되는 소스가 우선 — iconic → assembled_labeled →
   labeled_data_merged 순서).

출력 구조 (ultralytics detect 표준, 세 소스가 같은 images/labels 아래 섞여 들어감):
    datasets/rtdetr_full/
    ├── images/{train,val}/...
    ├── labels/{train,val}/...   (AABB)
    └── data.yaml

Train/Val 분할: CLAUDE.md 방침(Val 없이 Train/Test)에 따라 별도 curated val 셋은 아니고,
ultralytics 학습 파이프라인이 요구하는 val 경로를 채우기 위해 각 소스(그룹)마다 15%를
무작위로 떼어 val로 쓴다 (== 이 프로젝트에서 말하는 "Test"에 해당).

사용법:
    python src/detection/rt-detr/prepare_rtdetr_dataset.py \
        --iconic-images data/iconic \
        --iconic-labels data/labels/iconic \
        --assembled-images data/assembled_labeled/images \
        --assembled-labels data/assembled_labeled/labels \
        --labeled-data-images data/labeled_data_merged/images \
        --labeled-data-labels data/labeled_data_merged/labels \
        --output datasets/rtdetr_full \
        --val-ratio 0.15 \
        --seed 42

    특정 소스를 빼고 싶으면 해당 --*-images를 빈 문자열로 주면 된다.
"""

import argparse
import hashlib
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


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _split_and_copy(img_paths, label_lookup, output, val_ratio, convert_fn, source_name, seen_hashes):
    """
    img_paths를 train/val로 나눠서 output/images,labels 아래로 복사.
    convert_fn(label_path) -> AABB 라인 리스트 (OBB면 변환, 이미 AABB면 그대로 읽기만).
    seen_hashes: 이미 추가된 이미지의 md5 집합 (여러 소스에 걸쳐 공유, 중복 사진 스킵용).
    Returns: (train_count, val_count, skipped_no_label, skipped_duplicate)
    """
    img_paths = sorted(img_paths)
    random.shuffle(img_paths)
    n_val = max(1, round(len(img_paths) * val_ratio)) if img_paths else 0
    val_set = set(img_paths[:n_val])

    train_count = val_count = skipped = duplicate = 0
    for img_path in img_paths:
        label_path = label_lookup(img_path)
        if label_path is None or not label_path.exists():
            skipped += 1
            continue

        file_hash = _file_md5(img_path)
        if file_hash in seen_hashes:
            duplicate += 1
            continue
        seen_hashes.add(file_hash)

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

    extra = []
    if skipped:
        extra.append(f"라벨 없어서 {skipped}장 건너뜀")
    if duplicate:
        extra.append(f"중복 사진 {duplicate}장 건너뜀")
    suffix = f" ({', '.join(extra)})" if extra else ""
    print(f"[{source_name}] train {train_count} / val {val_count}{suffix}", flush=True)
    return train_count, val_count, skipped, duplicate


def read_aabb_lines(label_path: Path) -> list:
    """이미 AABB 포맷인 라벨을 그대로 읽기 (data/assembled_labeled, data/labeled_data_merged용)."""
    return [l for l in label_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


def _labeled_data_group(stem: str) -> str:
    """
    data/labeled_data_merged 파일명 접두사로 그룹을 나눈다 (train/val 분할 시 비율 유지용).
    merge_labeled_data.py의 SOURCES와 대응: 2_hole/3_hole/b_frame/5_hole = 픽킹(단일 부품),
    recipe1/2/3 = 조립 진행중 프레임(Model A/B/C).
    """
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
    return "labeled_data_other"


def build_dataset(iconic_images: Path, iconic_labels: Path,
                   assembled_images: Path, assembled_labels: Path,
                   labeled_data_images: Path, labeled_data_labels: Path,
                   output: Path, val_ratio: float, seed: int):
    random.seed(seed)

    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)

    total_train = 0
    total_val = 0
    skipped_no_label = 0
    skipped_duplicate = 0
    seen_hashes = set()

    # ── 1. data/iconic (OBB -> AABB 변환) ──────────────────────────
    for class_dir in sorted(iconic_images.iterdir()):
        if not class_dir.is_dir() or class_dir.name not in CLASS_NAMES:
            continue
        img_paths = [p for p in class_dir.iterdir() if p.suffix.lower() in IMG_EXTS]
        t, v, s, d = _split_and_copy(
            img_paths,
            lambda p: iconic_labels / f"{p.stem}.txt",
            output, val_ratio, convert_label_file, f"iconic/{class_dir.name}", seen_hashes,
        )
        total_train += t
        total_val += v
        skipped_no_label += s
        skipped_duplicate += d

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
            t, v, s, d = _split_and_copy(
                paths,
                lambda p: assembled_labels / f"{p.stem}.txt",
                output, val_ratio, read_aabb_lines, f"assembled_labeled/{group_name}", seen_hashes,
            )
            total_train += t
            total_val += v
            skipped_no_label += s
            skipped_duplicate += d

    # ── 3. data/labeled_data_merged (이미 AABB, canonical 클래스 ID로 변환됨) ──
    # ⚠️ 이 소스 중 구 data/labeled_data/train의 "C270 ..." 100장은 data/qwer ->
    # data/assembled_labeled로 이어진 것과 md5가 완전히 동일한 원본이라, 2번에서 이미
    # 추가된 뒤라 seen_hashes에 걸려 자동으로 스킵된다 (별도 필터링 불필요).
    if labeled_data_images and labeled_data_images.is_dir():
        all_paths = [p for p in labeled_data_images.iterdir() if p.suffix.lower() in IMG_EXTS]
        groups = {}
        for p in all_paths:
            groups.setdefault(_labeled_data_group(p.stem), []).append(p)

        for group_name, paths in sorted(groups.items()):
            t, v, s, d = _split_and_copy(
                paths,
                lambda p: labeled_data_labels / f"{p.stem}.txt",
                output, val_ratio, read_aabb_lines, f"labeled_data/{group_name}", seen_hashes,
            )
            total_train += t
            total_val += v
            skipped_no_label += s
            skipped_duplicate += d

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
    if skipped_duplicate:
        print(f"[정보] 중복 사진(md5 동일) 건너뜀: {skipped_duplicate}장", flush=True)
    print(f"data.yaml 저장: {data_yaml}", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="iconic+assembled_labeled+labeled_data_merged -> RT-DETR용 통합 데이터셋")
    parser.add_argument("--iconic-images", default="data/iconic")
    parser.add_argument("--iconic-labels", default="data/labels/iconic")
    parser.add_argument("--assembled-images", default="data/assembled_labeled/images",
                         help="빈 문자열로 주면 assembled_labeled 제외")
    parser.add_argument("--assembled-labels", default="data/assembled_labeled/labels")
    parser.add_argument("--labeled-data-images", default="data/labeled_data_merged/images",
                         help="빈 문자열로 주면 labeled_data_merged 제외")
    parser.add_argument("--labeled-data-labels", default="data/labeled_data_merged/labels")
    parser.add_argument("--output", default="datasets/rtdetr_full")
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_dataset(
        Path(args.iconic_images), Path(args.iconic_labels),
        Path(args.assembled_images) if args.assembled_images else None,
        Path(args.assembled_labels) if args.assembled_labels else None,
        Path(args.labeled_data_images) if args.labeled_data_images else None,
        Path(args.labeled_data_labels) if args.labeled_data_labels else None,
        Path(args.output), args.val_ratio, args.seed,
    )


if __name__ == "__main__":
    main()
