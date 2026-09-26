"""OBB 가중치를 test 149장에 돌려 발표에 쓸 표를 만든다 — mAP·클래스별 AP·각도 오차·CPU 속도. (ultralytics·torch 필요)

    python -m src.detection.evaluate_obb                                          # model/yolo_obb_parts.pt, data/dataset_obb/data.yaml
    python -m src.detection.evaluate_obb --weights runs\\obb\\yolo_obb_parts\\weights\\best.pt --split val
    python -m src.detection.evaluate_obb --no-bench                               # 속도 측정 생략

세 가지를 잰다:
  1. ultralytics val  — Precision / Recall / mAP50 / mAP50-95 (전체·클래스별). RT-DETR 표와 같은 자리에 넣는 값.
  2. 각도 오차        — 코어가 실제로 쓰는 건 박스가 아니라 '긴 변 방향' 이다. 정답 박스와 짝지어 긴 변 방향 차이(도)를 잰다.
                        볼트(육각)는 각도가 뜻이 없어 막대 3종만. 정답이 회전 박스인 사진(낱개 부품)만 믿을 수 있어 그것만 따로 집계한다.
  3. CPU 속도         — 시연 노트북엔 GPU 가 없다. 640 / 480 입력에서 한 장에 몇 ms 인지. 발표자료 '노트북 CPU' 칸에 쓴다.

결과: reports/detection_obb/report.md (발표용 표) · metrics.json · test_*.jpg (예측 그림)
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from .obb_labels import BAR_CLASSES, CLASS_NAMES, IMAGE_EXTS, angle_error_deg, is_axis_aligned, long_axis_angle, \
    parse_label_file, points_to_pixels, polygon_to_xywhr

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = ROOT / "model" / "yolo_obb_parts.pt"
DEFAULT_DATA = ROOT / "data" / "dataset_obb" / "data.yaml"
DEFAULT_REPORT = ROOT / "reports" / "detection_obb"

# 발표자료(04. 디텍션 모델 · 05. 디텍션 결과)에 이미 적혀 있는 값 — 같은 test 149장, AABB(회전 없는 박스) 기준
REFERENCE = {
    "RT-DETR-l (AABB)": {"precision": 0.980, "recall": 0.978, "map50": 0.986, "map": 0.830, "train": "10 epoch · 640px · GPU", "cpu": "한 장 1~2초"},
    "최종 AABB 모델": {"precision": 0.992, "recall": 0.982, "map50": 0.978, "map": 0.877, "train": "(팀 확인)", "cpu": "(팀 확인)",
                  "per_class_map50": {"part_3hole": 0.994, "bolt_1": 0.985, "mother_part": 0.985, "part_2hole": 0.985, "bolt_2": 0.941}},
}


def _yaml_paths(data: Path, split: str) -> tuple[Path, Path]:
    """data.yaml → (images 폴더, labels 폴더). yaml 파서 없이 줄만 읽는다."""
    kv = {}
    for line in data.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.strip().startswith(("#", "-")) and not line.startswith(" "):
            k, v = line.split(":", 1)
            kv[k.strip()] = v.split("#")[0].strip()
    base = Path(kv.get("path", data.parent))
    rel = kv.get(split, f"images/{split}")
    images = base / rel
    labels = base / rel.replace("images", "labels", 1) if "images" in rel else images.parent / "labels" / images.name
    return images, labels


def _names_of(model) -> dict[int, str]:
    names = dict(getattr(model, "names", {}) or {})
    try:                                           # 한글 이름 모델이면 코어 이름으로 바꿔 둔다
        mapping = json.loads((ROOT / "config" / "class_mapping.json").read_text(encoding="utf-8"))
        names = {i: mapping.get(n, n) for i, n in names.items()}
    except (OSError, ValueError):
        pass
    return {int(i): str(n) for i, n in names.items()}


# ── 1. mAP ────────────────────────────────────────────────────────────

def run_val(weights: Path, data: Path, split: str, imgsz: int, device, report_dir: Path) -> dict:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    m = model.val(data=str(data), split=split, imgsz=imgsz, device=device, plots=True, verbose=False,
                  project=str(ROOT / "runs" / "obb"), name=f"val_{split}", exist_ok=True)
    box = getattr(m, "box", m)
    names = _names_of(model)
    per_class = {}
    idx = list(getattr(box, "ap_class_index", []))
    for i, cid in enumerate(idx):
        try:
            p, r, ap50, ap = box.class_result(i)
        except Exception:                                   # 옛 버전
            p, r, ap50, ap = box.p[i], box.r[i], box.ap50[i], box.ap[i]
        per_class[names.get(int(cid), str(cid))] = {"precision": float(p), "recall": float(r), "map50": float(ap50), "map": float(ap)}
    try:
        mp, mr, map50, mAP = box.mean_results()
    except Exception:
        mp, mr, map50, mAP = box.mp, box.mr, box.map50, box.map
    speed = {k: round(float(v), 2) for k, v in (getattr(m, "speed", {}) or {}).items()}
    save_dir = Path(getattr(m, "save_dir", ROOT / "runs" / "obb" / f"val_{split}"))
    for f in ("val_batch0_pred.jpg", "val_batch1_pred.jpg", "confusion_matrix_normalized.png"):
        if (save_dir / f).exists():
            import shutil
            shutil.copy2(save_dir / f, report_dir / f"{split}_{f}")
    images_dir, _ = _yaml_paths(data, split)
    n_images = sum(1 for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS) if images_dir.is_dir() else None
    return {"split": split, "images": n_images,
            "precision": float(mp), "recall": float(mr), "map50": float(map50), "map": float(mAP),
            "per_class": per_class, "val_speed_ms": speed, "save_dir": str(save_dir), "names": names}


# ── 2. 각도 오차 ──────────────────────────────────────────────────────

def match_angles(weights: Path, data: Path, split: str, imgsz: int, device, conf: float, names: dict[int, str]) -> dict:
    """정답 막대(mother/part)마다 같은 클래스 예측 중 중심이 가장 가까운 것과 짝지어 긴 변 방향 차이를 잰다."""
    import cv2
    from ultralytics import YOLO

    images_dir, labels_dir = _yaml_paths(data, split)
    model = YOLO(str(weights))
    errors = defaultdict(list)          # (class, 'rotated'|'all') → [deg]
    n_gt = n_matched = 0
    for img_path in sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS):
        lp = labels_dir / f"{img_path.stem}.txt"
        if not lp.exists():
            continue
        gts = [g for g in parse_label_file(lp) if 0 <= g.class_id < len(CLASS_NAMES) and CLASS_NAMES[g.class_id] in BAR_CLASSES]
        if not gts:
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        r = model.predict(img, conf=conf, imgsz=imgsz, device=device, verbose=False)[0]
        preds = []
        if getattr(r, "obb", None) is not None and len(r.obb):
            for (cx, cy, bw, bh, ang), cid in zip(r.obb.xywhr.cpu().tolist(), r.obb.cls.cpu().tolist()):
                preds.append((names.get(int(cid), str(int(cid))), cx, cy, bw, bh, ang))
        for g in gts:
            n_gt += 1
            cname = CLASS_NAMES[g.class_id]
            gcx, gcy, gw, gh, gang = polygon_to_xywhr(points_to_pixels(g.points, w, h))
            best, best_d = None, 0.5 * max(gw, gh)
            for p in preds:
                if p[0] != cname:
                    continue
                d = math.hypot(p[1] - gcx, p[2] - gcy)
                if d < best_d:
                    best, best_d = p, d
            if best is None:
                continue
            n_matched += 1
            err = angle_error_deg(long_axis_angle(gw, gh, gang), long_axis_angle(best[3], best[4], best[5]))
            errors[(cname, "all")].append(err)
            if not is_axis_aligned(g.points):
                errors[(cname, "rotated")].append(err)

    def summarize(vals):
        if not vals:
            return {"n": 0}
        s = sorted(vals)
        return {"n": len(s), "mean": round(statistics.fmean(s), 2), "median": round(statistics.median(s), 2),
                "p90": round(s[min(len(s) - 1, int(0.9 * len(s)))], 2),
                "within_5deg": round(sum(v <= 5 for v in s) / len(s), 3), "within_10deg": round(sum(v <= 10 for v in s) / len(s), 3)}

    out = {"gt_bars": n_gt, "matched": n_matched, "conf": conf, "per_class": {}, "overall": {}}
    for kind in ("rotated", "all"):
        allv = []
        for c in BAR_CLASSES:
            v = errors.get((c, kind), [])
            allv += v
            out["per_class"].setdefault(c, {})[kind] = summarize(v)
        out["overall"][kind] = summarize(allv)
    return out


# ── 3. 속도 ───────────────────────────────────────────────────────────

def bench(weights: Path, data: Path, split: str, sizes=(640, 480), n: int = 30) -> dict:
    import cv2
    import torch
    from ultralytics import YOLO

    images_dir, _ = _yaml_paths(data, split)
    sample = next((p for p in sorted(images_dir.iterdir()) if p.suffix.lower() in IMAGE_EXTS), None)
    if sample is None:
        return {}
    img = cv2.imread(str(sample))
    devices = [("cpu", "cpu")] + ([("gpu", 0)] if torch.cuda.is_available() else [])
    out = {"image": sample.name, "threads": torch.get_num_threads(), "cpu": _cpu_name()}
    if torch.cuda.is_available():
        out["gpu"] = torch.cuda.get_device_name(0)
    for label, dev in devices:
        for s in sizes:
            model = YOLO(str(weights))                       # 장치를 바꿀 땐 새로 연다 (predict 는 처음 장치를 유지한다)
            for _ in range(5):
                model.predict(img, imgsz=s, device=dev, verbose=False)
            ts = []
            for _ in range(n):
                t = time.perf_counter(); model.predict(img, imgsz=s, device=dev, verbose=False); ts.append((time.perf_counter() - t) * 1000)
            ts.sort()
            out[f"{label}_{s}"] = {"median_ms": round(ts[len(ts) // 2], 1), "mean_ms": round(sum(ts) / len(ts), 1), "fps": round(1000 / (sum(ts) / len(ts)), 1)}
    return out


def _cpu_name() -> str:
    try:
        from ultralytics.utils.checks import get_cpu_info
        return get_cpu_info()
    except Exception:
        return platform.processor() or platform.machine()


# ── 보고서 ────────────────────────────────────────────────────────────

def _f(v, nd=3):
    return "—" if v is None else f"{v:.{nd}f}"


def report_markdown(val: dict, angles: dict | None, speed: dict | None, meta: dict | None, weights: Path) -> str:
    names = [val["names"].get(i, n) for i, n in enumerate(CLASS_NAMES)] if val.get("names") else list(CLASS_NAMES)
    ours = "YOLO-OBB (이번)"
    L = [f"# YOLO-OBB 결과 — {time.strftime('%Y-%m-%d %H:%M')}", "",
         f"- 가중치: `{weights}`   split: **{val['split']}**", ]
    if meta:
        L.append(f"- 학습: {meta.get('model')} · {meta.get('epochs_run')} epoch (best {meta.get('best_epoch')}) · "
                 f"{meta.get('cfg', {}).get('imgsz')}px · {meta.get('device')} · {meta.get('minutes')}분")
    L += ["", "## 04. 디텍션 모델 슬라이드용", "",
          f"| 항목 | RT-DETR-l (AABB) | 최종 AABB 모델 | **{ours}** |", "|---|---|---|---|"]
    r1, r2 = REFERENCE["RT-DETR-l (AABB)"], REFERENCE["최종 AABB 모델"]
    arch = f"{meta.get('model', 'YOLO-OBB')} · 회전 박스" if meta else "YOLO-OBB · 회전 박스"
    L.append(f"| 구조 | Transformer 디코더 · 큰 모델 | (팀 확인) | {arch} |")
    for key, label in (("precision", "Precision"), ("recall", "Recall"), ("map50", "mAP50"), ("map", "mAP50-95")):
        L.append(f"| {label} | {_f(r1[key])} | {_f(r2[key])} | **{_f(val[key])}** |")
    train_txt = f"{meta.get('epochs_run')} epoch · {meta.get('cfg', {}).get('imgsz')}px · {'GPU' if meta.get('device') != 'cpu' else 'CPU'}" if meta else "—"
    L.append(f"| 학습 | {r1['train']} | {r2['train']} | {train_txt} |")
    if speed and "cpu_640" in speed:
        cpu_txt = f"한 장 {speed['cpu_640']['median_ms']:.0f} ms (640) · {speed.get('cpu_480', {}).get('median_ms', float('nan')):.0f} ms (480)"
    else:
        cpu_txt = "—"
    L.append(f"| 노트북 CPU | {r1['cpu']} | {r2['cpu']} | {cpu_txt} |")
    L += ["", "RT-DETR·AABB 값은 발표자료에 적힌 값(같은 test 149장). AABB 는 회전 없는 IoU, OBB 는 회전 IoU 로 mAP 를 재므로 완전히 같은 잣대는 아니다.",
          "", "## 05. 디텍션 결과 슬라이드용 — 클래스별", "",
          "| 클래스 | Precision | Recall | AP50 | AP50-95 | AABB 모델 AP50 (참고) |", "|---|---|---|---|---|---|"]
    for n in names:
        pc = val["per_class"].get(n, {})
        ref = r2["per_class_map50"].get(n)
        L.append(f"| {n} | {_f(pc.get('precision'))} | {_f(pc.get('recall'))} | {_f(pc.get('map50'))} | {_f(pc.get('map'))} | {_f(ref)} |")
    weakest = min(val["per_class"].items(), key=lambda kv: kv[1]["map50"]) if val["per_class"] else None
    if weakest:
        L += ["", f"가장 약한 클래스: **{weakest[0]}** (AP50 {weakest[1]['map50']:.3f})"]
    if angles:
        L += ["", "## 각도 오차 (코어가 쓰는 '긴 변 방향', 도)", "",
              f"정답 막대 {angles['gt_bars']}개 중 {angles['matched']}개가 같은 클래스 예측과 짝지어짐 (conf ≥ {angles['conf']}). 180° 대칭이라 오차는 0~90.", "",
              "| 클래스 | 회전 라벨 n | 평균 | 중앙값 | p90 | ≤5° | ≤10° | 전체 n | 전체 평균 |", "|---|---|---|---|---|---|---|---|---|"]
        for c in BAR_CLASSES:
            r, a = angles["per_class"].get(c, {}).get("rotated", {"n": 0}), angles["per_class"].get(c, {}).get("all", {"n": 0})
            L.append(f"| {c} | {r['n']} | {_f(r.get('mean'), 1)} | {_f(r.get('median'), 1)} | {_f(r.get('p90'), 1)} | "
                     f"{_f(r.get('within_5deg') and r['within_5deg'] * 100, 0)}% | {_f(r.get('within_10deg') and r['within_10deg'] * 100, 0)}% | {a['n']} | {_f(a.get('mean'), 1)} |")
        o = angles["overall"]["rotated"]
        L += ["", f"회전 라벨 전체: n {o['n']}, 평균 {_f(o.get('mean'), 1)}°, 중앙값 {_f(o.get('median'), 1)}°, 10° 이내 {_f(o.get('within_10deg') and o['within_10deg'] * 100, 0)}%.",
              "'전체' 열은 회전 없는 직사각형 라벨(로보플로우 프레임)까지 넣은 값 — 그 라벨은 부품이 기울어져 있어도 0° 라서 오차가 과장된다."]
    if speed:
        L += ["", "## 속도 (한 장, 전처리+추론+후처리)", "", f"- CPU: {speed.get('cpu')}  (torch 스레드 {speed.get('threads')})"]
        if speed.get("gpu"):
            L.append(f"- GPU: {speed['gpu']}")
        L += ["", "| 장치·입력 | 중앙값 ms | 평균 ms | FPS |", "|---|---|---|---|"]
        for k, v in speed.items():
            if isinstance(v, dict):
                L.append(f"| {k.replace('_', ' ')} | {v['median_ms']} | {v['mean_ms']} | {v['fps']} |")
        L += ["", "시연 노트북은 이 PC 와 다르다 — 거기서 `python -m src.detection.evaluate_obb --bench-only` 로 다시 재서 적을 것."]
    if val.get("val_speed_ms"):
        L.append(f"\nultralytics val 속도(장당 ms): {val['val_speed_ms']}")
    L += ["", "그림: `test_val_batch0_pred.jpg`(예측), `test_confusion_matrix_normalized.png`."]
    return "\n".join(L) + "\n"


def run(weights: Path, data: Path, device="auto", imgsz: int = 640, split: str = "test", conf: float = 0.25,
        report_dir: Path = DEFAULT_REPORT, bench_speed: bool = True, do_val: bool = True, do_angles: bool = True) -> dict:
    from .train_yolo_obb import pick_device

    weights, data, report_dir = Path(weights), Path(data), Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    if not weights.exists():
        sys.exit(f"가중치가 없습니다: {weights}")
    if not data.exists():
        sys.exit(f"data.yaml 이 없습니다: {data}")
    device = pick_device(device)
    result = {"weights": str(weights), "data": str(data), "time": time.strftime("%Y-%m-%d %H:%M")}
    meta_path = report_dir / "train_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None

    val = None
    if do_val:
        print(f"\n[1/3] {split} 평가 (mAP) …")
        val = run_val(weights, data, split, imgsz, device, report_dir)
        result["val"] = val
        print(f"   P {val['precision']:.3f}  R {val['recall']:.3f}  mAP50 {val['map50']:.3f}  mAP50-95 {val['map']:.3f}")
        for n, pc in val["per_class"].items():
            print(f"   {n:12s} P {pc['precision']:.3f}  R {pc['recall']:.3f}  AP50 {pc['map50']:.3f}  AP50-95 {pc['map']:.3f}")
    angles = None
    if do_angles:
        print("\n[2/3] 각도 오차 …")
        names = val["names"] if val else _names_of(__import__("ultralytics").YOLO(str(weights)))
        angles = match_angles(weights, data, split, imgsz, device, conf, names)
        result["angles"] = angles
        o = angles["overall"]["rotated"]
        print(f"   회전 라벨 막대 {o['n']}개: 평균 {o.get('mean', float('nan'))}°, 10° 이내 {o.get('within_10deg', 0) * 100:.0f}%   (짝지음 {angles['matched']}/{angles['gt_bars']})")
    speed = None
    if bench_speed:
        print("\n[3/3] 속도 (CPU 640/480" + (", GPU" if device != "cpu" else "") + ") …")
        speed = bench(weights, data, split)
        result["speed"] = speed
        for k, v in speed.items():
            if isinstance(v, dict):
                print(f"   {k:8s} {v['median_ms']:6.1f} ms  ({v['fps']} fps)")

    (report_dir / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if val:
        (report_dir / "report.md").write_text(report_markdown(val, angles, speed, meta, weights), encoding="utf-8")
        print(f"\n보고서: {report_dir / 'report.md'}   (metrics.json, {split}_val_batch0_pred.jpg)")
    return result


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="YOLO-OBB 평가")
    ap.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--split", default="test", choices=["test", "val", "train"])
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--conf", type=float, default=0.25, help="각도 오차 잴 때 예측 신뢰도 문턱")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORT))
    ap.add_argument("--no-bench", action="store_true")
    ap.add_argument("--no-angles", action="store_true")
    ap.add_argument("--no-val", action="store_true", help="mAP 평가 생략 (각도·속도만)")
    ap.add_argument("--bench-only", action="store_true", help="속도만 잰다 (시연 노트북에서)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    if a.bench_only:
        a.no_val = a.no_angles = True
    run(Path(a.weights), Path(a.data), a.device, a.imgsz, a.split, a.conf, Path(a.report_dir),
        bench_speed=not a.no_bench, do_val=not a.no_val, do_angles=not a.no_angles)


if __name__ == "__main__":
    main()
