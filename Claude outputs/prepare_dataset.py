# src/detection/prepare_dataset.py
# ──────────────────────────────────────────────
# 원본 데이터 → YOLO OBB 학습용 폴더 구조로 변환
#
# 원본 구조:
#   data/iconic/{class_name}/{filename}.jpg
#   data/labels/iconic/{filename}.txt          ← OBB 라벨 (이미 완성)
#
# 출력 구조:
#   data/dataset/images/train|val|test/*.jpg
#   data/dataset/labels/train|val|test/*.txt
#   data/data.yaml
#
# 사용:
#   python src/detection/prepare_dataset.py
#   python src/detection/prepare_dataset.py --train 0.7 --val 0.15 --test 0.15
# ──────────────────────────────────────────────
import argparse
import random
import shutil
from collections import defaultdict
from pathlib import Path

# ── 클래스 정의 (라벨 파일 class_id 기준) ────
CLASS_NAMES = {
    0: "볼트_주황",
    1: "볼트_노랑",
    2: "나무_5구멍",
    3: "나무_3구멍",
    4: "나무_2구멍",
}

# ── 경로 ──────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent          # SmartFactory_Vision_Project2/
DATA_ROOT    = PROJECT_ROOT / "data"
IMG_ROOT     = DATA_ROOT / "iconic"              # iconic/{class_name}/*.jpg
LABEL_ROOT   = DATA_ROOT / "labels" / "iconic"  # labels/iconic/{stem}.txt
DATASET_OUT  = DATA_ROOT / "dataset"
YAML_OUT     = DATA_ROOT / "data.yaml"


def parse_args():
    p = argparse.ArgumentParser(description="Train/Val/Test 데이터셋 분할")
    p.add_argument("--train", type=float, default=0.70, help="학습 비율 (기본 0.70)")
    p.add_argument("--val",   type=float, default=0.15, help="검증 비율 (기본 0.15)")
    p.add_argument("--test",  type=float, default=0.15, help="테스트 비율 (기본 0.15)")
    p.add_argument("--seed",  type=int,   default=42,   help="랜덤 시드")
    p.add_argument("--clean", action="store_true",
                   help="기존 dataset/ 폴더 삭제 후 새로 생성")
    return p.parse_args()


def collect_samples() -> dict[str, list[tuple[Path, Path]]]:
    """
    클래스별로 (이미지 경로, 라벨 경로) 쌍 수집.
    라벨 파일명 = 이미지 파일명과 동일 (확장자만 .txt).
    """
    samples: dict[str, list[tuple[Path, Path]]] = defaultdict(list)
    missing_labels = []

    for class_dir in sorted(IMG_ROOT.iterdir()):
        if not class_dir.is_dir():
            continue
        class_name = class_dir.name
        for img_path in sorted(class_dir.glob("*.jpg")):
            label_path = LABEL_ROOT / (img_path.stem + ".txt")
            if not label_path.exists():
                missing_labels.append(img_path.stem)
                continue
            samples[class_name].append((img_path, label_path))

    if missing_labels:
        print(f"⚠️  라벨 없는 이미지 {len(missing_labels)}개 건너뜀: {missing_labels[:5]}...")

    return dict(samples)


def stratified_split(
    samples: dict[str, list],
    train_r: float, val_r: float, test_r: float,
    seed: int,
) -> tuple[list, list, list]:
    """클래스별 비율을 유지하는 stratified split."""
    rng = random.Random(seed)
    train_all, val_all, test_all = [], [], []

    for cls, pairs in samples.items():
        shuffled = list(pairs)
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_train = int(n * train_r)
        n_val   = int(n * val_r)
        # 나머지 전부 test
        train_all.extend(shuffled[:n_train])
        val_all.extend(shuffled[n_train : n_train + n_val])
        test_all.extend(shuffled[n_train + n_val :])
        print(f"  {cls:12s}  전체 {n:3d}  →  train {len(shuffled[:n_train]):3d} / "
              f"val {len(shuffled[n_train:n_train+n_val]):3d} / "
              f"test {len(shuffled[n_train+n_val:]):3d}")

    return train_all, val_all, test_all


def copy_split(pairs: list, img_dir: Path, lbl_dir: Path) -> None:
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    for img_path, lbl_path in pairs:
        shutil.copy2(img_path, img_dir / img_path.name)
        shutil.copy2(lbl_path, lbl_dir / lbl_path.name)


def write_data_yaml(nc: int, names: list[str]) -> None:
    content = f"""\
# data.yaml — YOLO OBB 학습 설정
# 자동 생성됨 (prepare_dataset.py)

path: {DATASET_OUT.resolve()}   # 데이터셋 루트 (절대 경로)
train: images/train
val:   images/val
test:  images/test

nc: {nc}
names:
"""
    for name in names:
        content += f"  - {name}\n"

    YAML_OUT.write_text(content, encoding="utf-8")
    print(f"\n✅ data.yaml 생성: {YAML_OUT}")


def main():
    args = parse_args()
    total_r = args.train + args.val + args.test
    assert abs(total_r - 1.0) < 1e-6, f"비율 합이 1.0이 아닙니다: {total_r}"

    if args.clean and DATASET_OUT.exists():
        shutil.rmtree(DATASET_OUT)
        print(f"🗑  기존 dataset/ 삭제: {DATASET_OUT}")

    print(f"\n📂 이미지: {IMG_ROOT}")
    print(f"📂 라벨:   {LABEL_ROOT}")
    print(f"📂 출력:   {DATASET_OUT}")
    print(f"📊 분할 비율: train={args.train:.0%}  val={args.val:.0%}  test={args.test:.0%}\n")

    # 1. 샘플 수집
    samples = collect_samples()
    if not samples:
        print("❌ 이미지/라벨 쌍을 찾을 수 없습니다. 경로를 확인하세요.")
        return

    total_imgs = sum(len(v) for v in samples.values())
    print(f"총 이미지-라벨 쌍: {total_imgs}개")

    # 2. Stratified split
    print("\n[클래스별 분할]")
    train_pairs, val_pairs, test_pairs = stratified_split(
        samples, args.train, args.val, args.test, args.seed
    )

    # 3. 파일 복사
    splits = {
        "train": train_pairs,
        "val":   val_pairs,
        "test":  test_pairs,
    }
    for split_name, pairs in splits.items():
        copy_split(
            pairs,
            DATASET_OUT / "images" / split_name,
            DATASET_OUT / "labels" / split_name,
        )

    print(f"\n✅ 복사 완료")
    print(f"  train: {len(train_pairs)}장")
    print(f"  val:   {len(val_pairs)}장")
    print(f"  test:  {len(test_pairs)}장")

    # 4. data.yaml 생성 (클래스 ID 순서로)
    sorted_names = [CLASS_NAMES[i] for i in sorted(CLASS_NAMES.keys())
                    if CLASS_NAMES[i] in samples]
    # 전체 클래스 포함 (없는 클래스도 유지해야 라벨 ID 정합성 유지)
    all_names = [CLASS_NAMES[i] for i in sorted(CLASS_NAMES.keys())]
    write_data_yaml(nc=len(all_names), names=all_names)

    print("\n다음 단계:")
    print("  python src/detection/train_yolo_obb.py")


if __name__ == "__main__":
    main()
