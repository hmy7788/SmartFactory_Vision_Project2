"""OBB 라벨 폴더 + 사진 폴더 → ultralytics 가 읽는 데이터셋 폴더 + data.yaml. (torch 없이 돈다)

    python -m src.detection.yolo11.prepare_obb_dataset --labels ..\\labels-20260926T031248Z-1-001 --images ..\\aabb\\images
    python -m src.detection.yolo11.prepare_obb_dataset --labels ..\\labels-20260926T031248Z-1-001            # 사진 폴더는 근처에서 찾는다
    python -m src.detection.yolo11.prepare_obb_dataset ... --val-frac 0        # val 을 안 떼고 test 를 val 로 (RT-DETR 때와 같은 방식)

받아들이는 폴더 모양 (라벨·사진 각각):
    <root>/train/*.txt          <root>/labels/train/*.txt          <root>/train/labels/*.txt      (test, val|valid 도 같은 식)
    <root>/train/*.jpg|png      <root>/images/train/*.jpg          <root>/train/images/*.jpg

무엇을 하나:
  1. 라벨 파일마다 같은 이름의 사진을 찾아 짝을 짓는다 (없으면 목록으로 알려 준다)
  2. 라벨을 한 줄씩 검사한다 — 9칸인지, 클래스 0~4 인지, 좌표가 0~1 인지, 넓이가 0 이 아닌지
  3. train 에서 묶음(bolt/part/model_a/recipe1_process…)별로 --val-frac 만큼 떼어 val 을 만든다 (test 149장은 손대지 않는다)
  4. data/dataset_obb/{images,labels}/{train,val,test} 로 복사하고 data.yaml, dataset_report.md/json, splits.json 을 쓴다

왜 val 을 따로 떼나: best.pt 를 고르는 기준이 test 면 test 점수가 낙관적이 된다(RT-DETR 때 그랬다).
   train 의 10% 를 val 로 두면 test 149장은 한 번도 안 본 사진이 된다. 같은 방식으로 비교하고 싶으면 --val-frac 0.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .obb_labels import (CLASS_NAMES, IMAGE_EXTS, KOREAN_NAMES, ObbLabel, check_label, find_image,
                         is_axis_aligned, parse_label_file, stem_group)

ROOT = Path(__file__).resolve().parents[3]
SPLIT_ALIASES = {"train": ("train",), "val": ("val", "valid"), "test": ("test",)}


@dataclass
class Sample:
    stem: str
    image: Path
    label: Path
    labels: list[ObbLabel]
    problems: list[str]
    split: str

    @property
    def group(self) -> str: return stem_group(self.stem)


# ── 폴더 찾기 ─────────────────────────────────────────────────────────

def _has_files(d: Path, exts) -> bool:
    return d.is_dir() and any(p.suffix.lower() in exts for p in d.iterdir())


def find_split_dir(root: Path, split: str, exts) -> Path | None:
    """root 아래에서 split(train/val/test) 파일이 든 폴더를 찾는다. 세 가지 모양을 다 본다."""
    kind = "labels" if ".txt" in exts else "images"
    for name in SPLIT_ALIASES[split]:
        for d in (root / name, root / kind / name, root / name / kind):
            if _has_files(d, exts):
                return d
    return None


def image_coverage(image_root: Path, stems: list[str], split: str) -> float:
    d = find_split_dir(image_root, split, IMAGE_EXTS)
    if d is None or not stems:
        return 0.0
    return sum(find_image(s, d) is not None for s in stems) / len(stems)


def guess_image_root(label_root: Path, stems_by_split: dict[str, list[str]]) -> tuple[Path | None, list[tuple[Path, float]]]:
    """--images 를 안 줬을 때: 프로젝트 옆(vision2)·data/ 아래에서 라벨 이름과 맞는 사진 폴더를 찾는다."""
    candidates: list[Path] = []
    for base in (ROOT.parent, ROOT / "data", label_root.parent):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and d.resolve() != label_root.resolve():
                candidates += [d, d / "images"]
    seen, scored = set(), []
    probe = stems_by_split.get("test") or stems_by_split.get("train") or []
    probe = probe[:: max(1, len(probe) // 40)][:40]            # 40장만 찔러 본다
    for d in candidates:
        r = d.resolve()
        if r in seen or not d.is_dir():
            continue
        seen.add(r)
        cov = image_coverage(d, probe, "test" if stems_by_split.get("test") else "train")
        if cov > 0:
            scored.append((d, cov))
    scored.sort(key=lambda t: -t[1])
    best = scored[0][0] if scored and scored[0][1] >= 0.9 else None
    return best, scored


# ── 수집·검사 ─────────────────────────────────────────────────────────

def collect(label_root: Path, image_root: Path, splits=("train", "test", "val"), tol: float = 0.0):
    """→ (samples, missing_images{split: [stem]}, unreadable{path: err})"""
    samples, missing, unreadable = [], defaultdict(list), {}
    for split in splits:
        ld = find_split_dir(label_root, split, (".txt",))
        if ld is None:
            continue
        idir = find_split_dir(image_root, split, IMAGE_EXTS)
        for lp in sorted(ld.glob("*.txt")):
            if lp.name.lower() in ("classes.txt", "labels.txt"):
                continue
            img = find_image(lp.stem, idir) if idir else None
            if img is None:
                missing[split].append(lp.stem)
                continue
            try:
                labels = parse_label_file(lp)
            except ValueError as e:
                unreadable[str(lp)] = str(e)
                continue
            problems = [f"{i + 1}행: {p}" for i, lb in enumerate(labels) for p in check_label(lb, tol=tol)]
            samples.append(Sample(lp.stem, img, lp, labels, problems, split))
    return samples, dict(missing), unreadable


def carve_val(samples: list[Sample], frac: float, seed: int) -> None:
    """train 에서 묶음별로 frac 만큼 val 로 옮긴다 (제자리 수정)."""
    if frac <= 0:
        return
    rng = random.Random(seed)
    by_group = defaultdict(list)
    for s in samples:
        if s.split == "train":
            by_group[s.group].append(s)
    for group in sorted(by_group):
        items = sorted(by_group[group], key=lambda s: s.stem)
        rng.shuffle(items)
        k = int(round(len(items) * frac))
        if len(items) >= 5:
            k = max(k, 1)
        for s in items[:k]:
            s.split = "val"


def stats(samples: list[Sample]) -> dict:
    out = {}
    for split in ("train", "val", "test"):
        ss = [s for s in samples if s.split == split]
        if not ss:
            continue
        inst, rotated, oob = Counter(), Counter(), 0
        for s in ss:
            for lb in s.labels:
                name = CLASS_NAMES[lb.class_id] if 0 <= lb.class_id < len(CLASS_NAMES) else f"?{lb.class_id}"
                inst[name] += 1
                if not is_axis_aligned(lb.points):
                    rotated[name] += 1
                if any(not (0 <= v <= 1) for p in lb.points for v in p):
                    oob += 1
        groups = Counter(s.group for s in ss)
        out[split] = {"images": len(ss), "instances": dict(inst), "rotated_instances": dict(rotated),
                      "out_of_bounds_points": oob, "groups": dict(sorted(groups.items())),
                      "images_with_problems": sum(1 for s in ss if s.problems)}
    return out


# ── 쓰기 ──────────────────────────────────────────────────────────────

def write_dataset(samples: list[Sample], out: Path, names: tuple[str, ...], val_is_test: bool, clip: bool) -> Path:
    from .obb_labels import clip_label

    for split in ("train", "val", "test"):
        for kind in ("images", "labels"):
            (out / kind / split).mkdir(parents=True, exist_ok=True)
    for s in samples:
        shutil.copy2(s.image, out / "images" / s.split / s.image.name)
        dst = out / "labels" / s.split / s.label.name
        if clip:
            dst.write_text("\n".join(clip_label(lb).to_line() for lb in s.labels) + "\n", encoding="utf-8")
        else:
            shutil.copy2(s.label, dst)
    yaml = out / "data.yaml"
    lines = ["# YOLO-OBB 학습 설정 — src/detection/yolo11/prepare_obb_dataset.py 가 만들었다",
             f"path: {out.resolve().as_posix()}", "train: images/train",
             f"val: {'images/test' if val_is_test else 'images/val'}", "test: images/test", "",
             f"nc: {len(names)}", "names:"] + [f"  {i}: {n}" for i, n in enumerate(names)]
    yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml


def report_markdown(st: dict, names, missing, unreadable, problems: list[str], yaml: Path, args, val_is_test: bool) -> str:
    keys = CLASS_NAMES                                    # stats 는 항상 영문 키
    val_note = ("test 를 val 로 사용 (RT-DETR 때와 같은 방식)" if args.val_frac <= 0 else
                f"train 이 너무 적어 val 을 못 떼고 test 를 val 로 사용" if val_is_test else
                f"train 에서 묶음별 {args.val_frac:.0%} 를 떼어냄 (seed {args.seed}) — best.pt 선택용. test 는 학습·선택에 안 쓴다")
    L = [f"# OBB 데이터셋 — {time.strftime('%Y-%m-%d %H:%M')}", "",
         f"- 라벨: `{args.labels}`", f"- 사진: `{args.images}`", f"- 출력: `{yaml.parent}`  (data.yaml: `{yaml.name}`)", f"- val: {val_note}", "",
         "| split | 사진 | " + " | ".join(names) + " | 회전 라벨 비율 |", "|---|---|" + "---|" * len(names) + "---|"]
    for split, v in st.items():
        total = sum(v["instances"].values()) or 1
        rot = sum(v["rotated_instances"].values())
        L.append(f"| {split} | {v['images']} | " + " | ".join(str(v["instances"].get(k, 0)) for k in keys) + f" | {rot / total:.0%} |")
    L += ["", "회전 라벨 비율 = 꼭짓점이 실제로 기울어진 박스의 비율. 낱개 부품 사진(auto_label_iconic)은 회전 박스, 로보플로우에서",
          "라벨한 프레임(조립 과정·픽킹·완성체)은 대부분 회전 없는 직사각형이다. 각도 정확도는 회전 라벨이 있는 사진으로만 잰다 (evaluate_obb).", ""]
    L += ["## 묶음별 장수", ""]
    for split, v in st.items():
        L.append(f"- {split}: " + ", ".join(f"{g} {n}" for g, n in v["groups"].items()))
    if missing:
        L += ["", "## 사진이 없는 라벨", ""] + [f"- {s}: {len(v)}장 (예: {', '.join(v[:5])})" for s, v in missing.items()]
    if unreadable:
        L += ["", "## 읽지 못한 라벨 파일", ""] + [f"- `{p}`: {e}" for p, e in unreadable.items()]
    if problems:
        L += ["", f"## 라벨 검사에서 걸린 것 ({len(problems)}건)", ""] + [f"- {p}" for p in problems[:60]]
        if len(problems) > 60:
            L.append(f"- … 외 {len(problems) - 60}건 (dataset_report.json)")
    return "\n".join(L) + "\n"


def build(args) -> Path:
    label_root = Path(args.labels)
    if not any(find_split_dir(label_root, s, (".txt",)) for s in ("train", "test")):
        sys.exit(f"라벨 폴더에서 train/test 를 못 찾았습니다: {label_root}  (train\\*.txt 또는 labels\\train\\*.txt 모양이어야 함)")
    stems = {s: [p.stem for p in find_split_dir(label_root, s, (".txt",)).glob("*.txt")]
             for s in ("train", "test") if find_split_dir(label_root, s, (".txt",))}
    if args.images:
        image_root = Path(args.images)
    else:
        image_root, scored = guess_image_root(label_root, stems)
        if image_root is None:
            tried = "\n".join(f"   {d}  (이름 일치 {c:.0%})" for d, c in scored[:8]) or "   (근처에 사진 폴더가 없음)"
            sys.exit("사진 폴더를 못 찾았습니다. --images 로 알려 주세요 (라벨과 같은 이름의 .jpg/.png 가 train/, test/ 아래 있어야 함).\n"
                     f"   찾아본 곳:\n{tried}\n   예: --images ..\\aabb\\images")
        print(f"사진 폴더 (자동): {image_root}")
    args.images = str(image_root)

    samples, missing, unreadable = collect(label_root, image_root, tol=args.tol)
    if not samples:
        sys.exit(f"라벨과 짝이 맞는 사진이 한 장도 없습니다. 라벨: {label_root}  사진: {image_root}")
    problems = [f"{s.split}/{s.stem}: {p}" for s in samples for p in s.problems]
    if args.strict and (problems or missing or unreadable):
        sys.exit(f"--strict: 라벨 문제 {len(problems)}건, 사진 없는 라벨 {sum(map(len, missing.values()))}장, 못 읽은 파일 {len(unreadable)}개")

    has_val = any(s.split == "val" for s in samples)
    if not has_val:
        carve_val(samples, args.val_frac, args.seed)
    names = KOREAN_NAMES if args.korean_names else CLASS_NAMES
    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    val_is_test = not any(s.split == "val" for s in samples)
    yaml = write_dataset(samples, out, names, val_is_test=val_is_test, clip=args.clip)

    st = stats(samples)
    (out / "splits.json").write_text(json.dumps({sp: sorted(s.stem for s in samples if s.split == sp) for sp in ("train", "val", "test")},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "dataset_report.json").write_text(json.dumps({"stats": st, "missing_images": missing, "unreadable": unreadable,
                                                         "problems": problems, "names": list(names), "labels": str(label_root),
                                                         "images": str(image_root), "val_frac": args.val_frac, "seed": args.seed},
                                                        ensure_ascii=False, indent=1), encoding="utf-8")
    md = report_markdown(st, names, missing, unreadable, problems, yaml, args, val_is_test)
    (out / "dataset_report.md").write_text(md, encoding="utf-8")

    print()
    for split, v in st.items():
        rot = sum(v["rotated_instances"].values()); total = sum(v["instances"].values()) or 1
        print(f"  {split:5s} {v['images']:4d}장  " + "  ".join(f"{n} {v['instances'].get(k, 0)}" for n, k in zip(names, CLASS_NAMES))
              + f"   회전 라벨 {rot / total:.0%}")
    if missing:
        print(f"  사진 없는 라벨: " + ", ".join(f"{s} {len(v)}장" for s, v in missing.items()) + "  → dataset_report.md")
    if unreadable:
        print(f"  못 읽은 라벨 파일 {len(unreadable)}개 → dataset_report.md")
    if problems:
        print(f"  라벨 검사에서 걸린 것 {len(problems)}건 (이미지 밖 꼭짓점 등) → dataset_report.md")
    print(f"  val: {'test 를 val 로 씀' if val_is_test else 'train 에서 떼어냄'}")
    print(f"\ndata.yaml: {yaml}\n다음:  python -m src.detection.yolo11.train_yolo_obb --data \"{yaml}\"")
    return yaml


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="OBB 라벨 + 사진 → ultralytics 데이터셋")
    ap.add_argument("--labels", required=True, help="OBB 라벨 폴더 (train/, test/ 가 있는 곳)")
    ap.add_argument("--images", default=None, help="사진 폴더 (train/, test/). 생략하면 근처에서 찾는다")
    ap.add_argument("--out", default=str(ROOT / "data" / "dataset_obb"))
    ap.add_argument("--val-frac", type=float, default=0.10, help="train 에서 val 로 떼는 비율. 0 이면 test 를 val 로 씀")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tol", type=float, default=0.05, help="꼭짓점이 이 만큼은 화면 밖으로 나가도 문제로 안 잡음")
    ap.add_argument("--clip", action="store_true", help="화면 밖 꼭짓점을 0~1 로 자른 라벨을 쓴다 (기본: 원본 그대로 복사)")
    ap.add_argument("--korean-names", action="store_true", help="data.yaml 에 한글 클래스 이름을 쓴다 (기본 영문 bolt_2 …)")
    ap.add_argument("--strict", action="store_true", help="라벨 문제가 하나라도 있으면 멈춘다")
    ap.add_argument("--clean", action="store_true", help="출력 폴더를 지우고 새로 만든다")
    return ap.parse_args(argv)


def main(argv=None):
    build(parse_args(argv))


if __name__ == "__main__":
    main()
