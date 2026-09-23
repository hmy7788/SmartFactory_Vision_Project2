"""
prepare_obb_dataset.py

메인 파이프라인(YOLO-OBB, CLAUDE.md 3-1에 OBB로 확정된 포맷)용 통합 데이터셋 준비 스크립트.
rt-detr/prepare_rtdetr_dataset.py(AABB 버전)와 소스·그룹핑·중복 제거 로직은 동일하고
라벨 포맷만 다르다 — 같은 데이터를 형식만 바꿔 두 버전(AABB/OBB)으로 각각 만든다.

세 소스를 합친다:
  1. data/iconic/ — 원본이 이미 OBB(cv2.minAreaRect로 라벨링)라 변환 없이 그대로 복사.
  2. data/assembled_labeled/ — 원본이 Roboflow AABB라 실제 회전각 정보가 없다.
     ⚠️ 회전 없는 사각형(axis-aligned)을 4꼭짓점 OBB 포맷으로 그대로 펼쳐서 저장한다
     (rotation=0인 퇴화 OBB). 실제 부품이 비스듬히 놓여 있어도 진짜 minAreaRect처럼
     꼭 맞게 감싸지 못하고 iconic 소스보다 헐겁다 — 애초에 회전 라벨이 없어서 생기는
     한계이고 이 스크립트가 복원할 수 있는 정보가 아니다.
  3. data/labeled_data_merged/ — 2번과 동일한 이유로 동일하게 처리 (Roboflow AABB 원본).

⚠️ 중복 제거: prepare_rtdetr_dataset.py와 동일하게, data/labeled_data_merged의 구
   "C270 ..." 100장은 data/qwer -> data/assembled_labeled와 md5가 동일한 원본이라
   먼저 처리되는 소스(iconic -> assembled_labeled -> labeled_data_merged 순)가 우선이고
   나머지는 자동 스킵된다.

출력 (ultralytics obb 표준):
    datasets/yolo_obb_full/
    ├── images/{train,val}/...
    ├── labels/{train,val}/...   (OBB: class x1 y1 x2 y2 x3 y3 x4 y4, 0~1 정규화)
    └── data.yaml

Train/Val 분할: prepare_rtdetr_dataset.py와 동일하게 소스(그룹)별로 15%씩 무작위 val.

사용법:
    python src/detection/prepare_obb_dataset.py
    python src/detection/prepare_obb_dataset.py --output datasets/yolo_obb_full --val-ratio 0.15
"""

import argparse
import hashlib
import random
import shutil
import sys
from pathlib import Path

CLASS_NAMES = ["bolt_2", "bolt_1", "mother_part", "part_3hole", "part_2hole"]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def aabb_line_to_obb_line(line: str) -> str:
    """'class xc yc w h' (0~1) -> 'class x1 y1 x2 y2 x3 y3 x4 y4' (0~1, rotation=0 퇴화 사각형)."""
    parts = line.strip().split()
    class_id = parts[0]
    xc, yc, w, h = map(float, parts[1:5])
    x1, y1 = xc - w / 2, yc - h / 2  # top-left
    x2, y2 = xc + w / 2, yc - h / 2  # top-right
    x3, y3 = xc + w / 2, yc + h / 2  # bottom-right
    x4, y4 = xc - w / 2, yc + h / 2  # bottom-left
    coords = [x1, y1, x2, y2, x3, y3, x4, y4]
    coords = [min(max(c, 0.0), 1.0) for c in coords]
    return f"{class_id} " + " ".join(f"{c:.6f}" for c in coords)


def convert_aabb_file_to_obb(src_path: Path) -> list:
    return [aabb_line_to_obb_line(l) for l in src_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


def read_obb_lines(src_path: Path) -> list:
    """이미 OBB 포맷인 라벨을 그대로 읽기 (data/iconic용)."""
    return [l for l in src_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _split_and_copy(img_paths, label_lookup, output, val_ratio, convert_fn, source_name, seen_hashes):
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

        obb_lines = convert_fn(label_path)
        split = "val" if img_path in val_set else "train"

        dst_img = output / "images" / split / img_path.name
        dst_label = output / "labels" / split / f"{img_path.stem}.txt"
        shutil.copy2(img_path, dst_img)
        dst_label.write_text("\n".join(obb_lines), encoding="utf-8")

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


def _labeled_data_group(stem: str) -> str:
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

    total_train = total_val = skipped_no_label = skipped_duplicate = 0
    seen_hashes = set()

    # ── 1. data/iconic (원본이 이미 OBB) ────────────────────────────
    for class_dir in sorted(iconic_images.iterdir()):
        if not class_dir.is_dir() or class_dir.name not in CLASS_NAMES:
            continue
        img_paths = [p for p in class_dir.iterdir() if p.suffix.lower() in IMG_EXTS]
        t, v, s, d = _split_and_copy(
            img_paths,
            lambda p: iconic_labels / f"{p.stem}.txt",
            output, val_ratio, read_obb_lines, f"iconic/{class_dir.name}", seen_hashes,
        )
        total_train += t; total_val += v; skipped_no_label += s; skipped_duplicate += d

    # ── 2. data/assembled_labeled (AABB -> 퇴화 OBB) ────────────────
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
                output, val_ratio, convert_aabb_file_to_obb, f"assembled_labeled/{group_name}", seen_hashes,
            )
            total_train += t; total_val += v; skipped_no_label += s; skipped_duplicate += d

    # ── 3. data/labeled_data_merged (AABB -> 퇴화 OBB) ──────────────
    if labeled_data_images and labeled_data_images.is_dir():
        all_paths = [p for p in labeled_data_images.iterdir() if p.suffix.lower() in IMG_EXTS]
        groups = {}
        for p in all_paths:
            groups.setdefault(_labeled_data_group(p.stem), []).append(p)
        for group_name, paths in sorted(groups.items()):
            t, v, s, d = _split_and_copy(
                paths,
                lambda p: labeled_data_labels / f"{p.stem}.txt",
                output, val_ratio, convert_aabb_file_to_obb, f"labeled_data/{group_name}", seen_hashes,
            )
            total_train += t; total_val += v; skipped_no_label += s; skipped_duplicate += d

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

    parser = argparse.ArgumentParser(description="iconic(OBB)+assembled_labeled(AABB->OBB)+labeled_data_merged(AABB->OBB) -> YOLO-OBB용 통합 데이터셋")
    parser.add_argument("--iconic-images", default="data/iconic")
    parser.add_argument("--iconic-labels", default="data/labels/iconic")
    parser.add_argument("--assembled-images", default="data/assembled_labeled/images")
    parser.add_argument("--assembled-labels", default="data/assembled_labeled/labels")
    parser.add_argument("--labeled-data-images", default="data/labeled_data_merged/images")
    parser.add_argument("--labeled-data-labels", default="data/labeled_data_merged/labels")
    parser.add_argument("--output", default="datasets/yolo_obb_full")
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
