"""
merge_labeled_data.py

data/labeled_data/의 Roboflow 내보내기(AABB/Darknet 포맷) 서브폴더들을 프로젝트 canonical
클래스 ID 체계로 변환해서 하나로 합친다.

⚠️ 왜 필요한가 (docs 리뷰에서 발견한 문제):
   - `train`의 `_darknet.labels`: 0=bolt_1, 1=bolt_2, 2=mother_part, 3=part_2hole, 4=part_3hole
   - 프로젝트 전체(data/iconic, data/assembled_labeled, RT-DETR 학습)가 쓰는 CLASS_TO_ID:
     0=bolt_2, 1=bolt_1, 2=mother_part, 3=part_3hole, 4=part_2hole
   → bolt_1/bolt_2, part_2hole/part_3hole가 서로 반대로 번호 매겨져 있어 그대로 합치면 안 됨.
   - `2_hole_label`/`3_hole_label`/`b1_label`/`train3`은 `_darknet.labels`가 없어 숫자만으로는
     알 수 없음 — 이미지 내용을 직접 확인해서 폴더당 단일 클래스임을 검증했다 (아래 SOURCES 참고).

`train2`는 `train`과 100장이 파일명(Roboflow 해시)까지 완전히 동일한 중복이라 제외한다
(포함 시 train/val 분할에서 같은 프레임이 양쪽에 들어가는 데이터 누수 발생).

사용법:
    python src/detection/merge_labeled_data.py
    python src/detection/merge_labeled_data.py --output data/labeled_data_merged
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# 프로젝트 canonical 매핑 (auto_label_iconic.py, prepare_rtdetr_dataset.py와 동일)
CLASS_TO_ID = {"bolt_2": 0, "bolt_1": 1, "mother_part": 2, "part_3hole": 3, "part_2hole": 4}


def _normalize_name(name: str) -> str:
    """'bolt1' / 'bolt_1' / 'BOLT_1' 등 표기 차이를 canonical 이름으로 통일."""
    n = name.strip().lower().replace("_", "").replace(" ", "")
    table = {
        "bolt1": "bolt_1", "bolt2": "bolt_2",
        "motherpart": "mother_part", "mother": "mother_part",
        "part2hole": "part_2hole", "part2": "part_2hole",
        "part3hole": "part_3hole", "part3": "part_3hole",
    }
    if n not in table:
        raise ValueError(f"알 수 없는 클래스 이름: {name!r}")
    return table[n]


# 각 소스 폴더 처리 방식.
#   "single": _darknet.labels가 없는 폴더 — 폴더 전체가 이 클래스 하나뿐임을 이미지로 직접 검증함.
#             (안전장치: 실제로 폴더 안에 다른 local id가 섞여 있으면 스크립트가 에러를 낸다)
#   "darknet_labels": 폴더 안의 _darknet.labels 파일을 읽어 local id -> 이름 매핑을 구성.
SOURCES = {
    "2_hole_label": {"mode": "single", "class_name": "part_2hole"},
    "3_hole_label": {"mode": "single", "class_name": "part_3hole"},
    "b1_label": {"mode": "single", "class_name": "bolt_1"},
    "train3": {"mode": "single", "class_name": "mother_part"},
    "train": {"mode": "darknet_labels"},
    # train2는 의도적으로 제외 (train과 100장 완전 중복, 아래 docstring 참고)
}


def build_local_to_canonical(folder: Path, config: dict) -> dict:
    """이 폴더의 local class id -> canonical class id 매핑을 만든다."""
    if config["mode"] == "single":
        canonical_id = CLASS_TO_ID[config["class_name"]]
        # 실제로 폴더 안에 쓰인 local id들을 전부 스캔해서, 정말 단일 클래스인지 재확인.
        local_ids = set()
        for label_path in folder.glob("*.txt"):
            if label_path.name == "_darknet.labels":
                continue
            for line in label_path.read_text(encoding="utf-8").strip().splitlines():
                if line.strip():
                    local_ids.add(int(line.split()[0]))
        if len(local_ids) != 1:
            raise ValueError(
                f"{folder.name}: 'single' 모드인데 local class id가 여러 개 발견됨({local_ids}) "
                f"— SOURCES 설정을 다시 확인해야 함"
            )
        return {local_ids.pop(): canonical_id}

    if config["mode"] == "darknet_labels":
        labels_file = folder / "_darknet.labels"
        names = labels_file.read_text(encoding="utf-8").strip().splitlines()
        return {i: CLASS_TO_ID[_normalize_name(name)] for i, name in enumerate(names)}

    raise ValueError(f"알 수 없는 mode: {config['mode']}")


def convert_label_file(src_path: Path, local_to_canonical: dict) -> list:
    lines = []
    for line in src_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        parts = line.split()
        local_id = int(parts[0])
        canonical_id = local_to_canonical[local_id]
        lines.append(" ".join([str(canonical_id)] + parts[1:]))
    return lines


def merge(data_root: Path, output: Path):
    images_out = output / "images"
    labels_out = output / "labels"
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    per_class_boxes = {name: 0 for name in CLASS_TO_ID}
    total_images = 0
    skipped_existing = 0

    for folder_name, config in SOURCES.items():
        folder = data_root / folder_name
        if not folder.is_dir():
            print(f"[경고] 폴더 없음, 건너뜀: {folder}", flush=True)
            continue

        local_to_canonical = build_local_to_canonical(folder, config)
        canonical_names = {v: k for k, v in CLASS_TO_ID.items()}

        img_paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXTS)
        folder_boxes = 0
        for img_path in img_paths:
            label_path = folder / f"{img_path.stem}.txt"
            if not label_path.exists():
                print(f"[경고] 라벨 없음, 건너뜀: {img_path}", flush=True)
                continue

            dst_img = images_out / img_path.name
            dst_label = labels_out / f"{img_path.stem}.txt"
            if dst_img.exists() or dst_label.exists():
                print(f"[경고] 이미 존재해서 건너뜀(파일명 충돌): {img_path.name}", flush=True)
                skipped_existing += 1
                continue

            converted = convert_label_file(label_path, local_to_canonical)
            shutil.copy2(img_path, dst_img)
            dst_label.write_text("\n".join(converted), encoding="utf-8")

            total_images += 1
            folder_boxes += len(converted)
            for line in converted:
                canonical_id = int(line.split()[0])
                per_class_boxes[canonical_names[canonical_id]] += 1

        print(f"[{folder_name}] {len(img_paths)}장 병합, 박스 {folder_boxes}개", flush=True)

    print(f"\n[완료] 총 {total_images}장 -> {output}", flush=True)
    if skipped_existing:
        print(f"[경고] 파일명 충돌로 건너뜀: {skipped_existing}장", flush=True)
    print("클래스별 박스 개수:", flush=True)
    for name, count in per_class_boxes.items():
        print(f"  {name}: {count}", flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="data/labeled_data 서브폴더들을 canonical 클래스 ID로 병합 (train2 제외)")
    parser.add_argument("--data-root", default=str(REPO_ROOT / "data" / "labeled_data"))
    parser.add_argument("--output", default=str(REPO_ROOT / "data" / "labeled_data_merged"))
    args = parser.parse_args()

    merge(Path(args.data_root), Path(args.output))


if __name__ == "__main__":
    main()
