"""YOLO-OBB 학습 → model/yolo_obb_parts.pt → test 149장 평가까지 한 번에. (ultralytics·torch 필요)

    python -m src.detection.train_yolo_obb                                   # data/dataset_obb/data.yaml 로 100 epoch
    python -m src.detection.train_yolo_obb --model yolov8n-obb.pt --epochs 150
    python -m src.detection.train_yolo_obb --device cpu --batch 8 --epochs 30 # GPU 없는 노트북
    python -m src.detection.train_yolo_obb --resume                          # 끊긴 학습 이어서

먼저:  python -m src.detection.prepare_obb_dataset --labels ..\\labels-… --images ..\\aabb\\images
끝나면: model/yolo_obb_parts.pt (코어·웹 UI 가 바로 읽는 자리), reports/detection_obb/ (train_log.txt, results.csv, report.md)

설정에서 판단한 것 (바꿀 땐 이유를 같이 바꿀 것):
  degrees=180   OBB 의 존재 이유가 각도다. 부품은 아무 방향으로 놓이므로 회전을 다 보여 준다.
  fliplr=0.5    좌우 반전한 3구는 여전히 3구다 — 디텍터는 '무엇이 어디'만 답하고 좌우 판정은 코어가 하므로 안전하다.
  flipud=0      회전 180 + 좌우 반전이면 상하 반전은 이미 포함된다.
  hsv_h=0.01    노랑/주황 볼트는 색으로만 갈린다. 색조를 흔들면 정답이 바뀐다. 밝기·채도만 흔든다.
  scale=0.2     카메라 높이가 고정이라 크기가 단서다(2구 vs 3구 길이). 크게 흔들지 않는다.
  mosaic=0.5    낱개 부품 사진을 붙여 여러 부품이 한 화면에 있는 장면을 만든다 (test 는 조립 장면이 많다).
  copy_paste=0  OBB 폴리곤을 뒤집어 붙이는 증강 — 결과가 어색해서 끈다.
  patience=30   val 이 30 epoch 동안 안 좋아지면 멈춘다. epochs 보다 작아야 뜻이 있다.
  seed·deterministic  같은 설정이면 같은 결과가 나오게. 발표 수치는 재현되어야 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "data" / "dataset_obb" / "data.yaml"
DEFAULT_OUT = ROOT / "model" / "yolo_obb_parts.pt"
DEFAULT_REPORT = ROOT / "reports" / "detection_obb"

TRAIN_CFG = dict(
    task="obb", imgsz=640, epochs=100, batch=16, patience=30,
    optimizer="auto", cos_lr=False, close_mosaic=10, warmup_epochs=3,
    hsv_h=0.010, hsv_s=0.30, hsv_v=0.30, degrees=180.0, translate=0.10, scale=0.20, shear=0.0, perspective=0.0,
    fliplr=0.5, flipud=0.0, mosaic=0.5, mixup=0.0, copy_paste=0.0,
    plots=True, save=True, verbose=True, exist_ok=True, deterministic=True, amp=True,
)


class Tee:
    """콘솔에 그대로 쓰고 파일에도 남긴다. 진행 막대(\\r 로 덮어쓰는 줄)는 마지막 상태만 파일에 남긴다."""

    def __init__(self, stream, path: Path):
        self.stream, self.file = stream, open(path, "a", encoding="utf-8", errors="replace")

    def write(self, s):
        self.stream.write(s)
        if "\r" in s:
            s = s.rsplit("\r", 1)[-1]
            if not s.endswith("\n"):
                return len(s)
        self.file.write(s); self.file.flush()
        return len(s)

    def flush(self): self.stream.flush(); self.file.flush()

    def __getattr__(self, name): return getattr(self.stream, name)


def pick_device(arg: str):
    if arg not in ("auto", ""):
        return arg
    try:
        import torch
        return 0 if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def default_workers() -> int:
    n = os.cpu_count() or 4
    return min(4, max(1, n // 2)) if platform.system() == "Windows" else min(8, n)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="YOLO-OBB 학습")
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--model", default="yolo11n-obb.pt", help="시작 가중치: yolo11n-obb.pt / yolov8n-obb.pt / yolo11s-obb.pt …")
    ap.add_argument("--epochs", type=int, default=TRAIN_CFG["epochs"])
    ap.add_argument("--batch", type=int, default=TRAIN_CFG["batch"])
    ap.add_argument("--imgsz", type=int, default=TRAIN_CFG["imgsz"])
    ap.add_argument("--patience", type=int, default=TRAIN_CFG["patience"])
    ap.add_argument("--device", default="auto", help="auto / 0 / cpu")
    ap.add_argument("--workers", type=int, default=None, help="데이터 로더 프로세스 수 (윈도우 기본 2~4)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default="yolo_obb_parts", help="runs/obb/<name>/ 에 학습 산출물")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="best.pt 를 복사할 자리")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORT))
    ap.add_argument("--resume", action="store_true", help="runs/obb/<name>/weights/last.pt 에서 이어서")
    ap.add_argument("--no-eval", action="store_true", help="학습만 하고 test 평가는 건너뜀")
    ap.add_argument("--no-bench", action="store_true", help="평가 때 CPU 속도 측정을 건너뜀")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VAL", help="ultralytics 인자 덮어쓰기 (예: --set lr0=0.005 mosaic=1.0)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    report_dir = Path(a.report_dir); report_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = Tee(sys.stdout, report_dir / "train_log.txt")      # ultralytics 로거보다 먼저 걸어야 로그가 파일에도 남는다
    sys.stderr = Tee(sys.stderr, report_dir / "train_log.txt")
    print(f"\n=== {time.strftime('%Y-%m-%d %H:%M')}  train_yolo_obb {' '.join(sys.argv[1:] if argv is None else argv)}")

    data = Path(a.data)
    if not data.exists():
        sys.exit(f"data.yaml 이 없습니다: {data}\n   먼저: python -m src.detection.prepare_obb_dataset --labels <라벨 폴더> --images <사진 폴더>")
    try:
        import torch
        from ultralytics import YOLO
        import ultralytics
    except ImportError as e:
        sys.exit(f"{e}\n   pip install ultralytics   (GPU 면 torch 를 CUDA 판으로 먼저: https://pytorch.org/get-started/locally/)")

    device = pick_device(a.device)
    gpu = torch.cuda.get_device_name(0) if device != "cpu" and torch.cuda.is_available() else None
    print(f"torch {torch.__version__}  ultralytics {ultralytics.__version__}  장치: {gpu or 'CPU'}   data: {data}")

    cfg = dict(TRAIN_CFG)
    cfg.update(data=str(data), epochs=a.epochs, batch=a.batch, imgsz=a.imgsz, patience=a.patience, device=device,
               workers=a.workers if a.workers is not None else default_workers(), seed=a.seed,
               project=str(ROOT / "runs" / "obb"), name=a.name)
    for kv in a.set:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except ValueError:
            pass
        cfg[k] = v
    if device == "cpu" and cfg["batch"] > 8:
        print(f"CPU 라서 batch 를 {cfg['batch']} → 8 로 줄입니다 (메모리)"); cfg["batch"] = 8

    run_dir = Path(cfg["project"]) / cfg["name"]
    if a.resume:
        last = run_dir / "weights" / "last.pt"
        if not last.exists():
            sys.exit(f"--resume: {last} 가 없습니다")
        model = YOLO(str(last)); cfg = {"resume": True}
        print(f"이어서 학습: {last}")
    else:
        model = YOLO(a.model)
    print("설정: " + json.dumps({k: cfg[k] for k in sorted(cfg) if k not in ("project", "data")}, ensure_ascii=False))

    t0 = time.time()
    model.train(**cfg)
    took = time.time() - t0
    save_dir = Path(getattr(getattr(model, "trainer", None), "save_dir", run_dir))
    best = save_dir / "weights" / "best.pt"
    if not best.exists():
        sys.exit(f"best.pt 가 없습니다: {best}  (학습이 중간에 끊겼으면 --resume)")

    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out)
    for f in ("results.csv", "results.png", "confusion_matrix_normalized.png", "labels.jpg", "val_batch0_pred.jpg"):
        if (save_dir / f).exists():
            shutil.copy2(save_dir / f, report_dir / f)

    best_epoch, epochs_run = _best_epoch(save_dir / "results.csv")
    meta = {"time": time.strftime("%Y-%m-%d %H:%M"), "model": a.model, "data": str(data), "device": gpu or "cpu",
            "epochs_requested": a.epochs, "epochs_run": epochs_run, "best_epoch": best_epoch, "minutes": round(took / 60, 1),
            "cfg": {k: v for k, v in cfg.items() if k not in ("project",)}, "run_dir": str(save_dir), "weights": str(out),
            "torch": torch.__version__, "ultralytics": ultralytics.__version__}
    (report_dir / "train_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n학습 끝: {took / 60:.1f}분, {epochs_run} epoch (best {best_epoch})   가중치: {out}   로그: {report_dir / 'train_log.txt'}")

    if not a.no_eval:
        from .evaluate_obb import run as evaluate
        evaluate(weights=out, data=data, device=device, imgsz=a.imgsz, report_dir=report_dir, bench_speed=not a.no_bench)


def _best_epoch(results_csv: Path) -> tuple[int | None, int | None]:
    """results.csv 에서 val mAP50-95 가 가장 높은 epoch 과 돈 epoch 수."""
    if not results_csv.exists():
        return None, None
    import csv
    rows = list(csv.DictReader(open(results_csv, encoding="utf-8")))
    rows = [{k.strip(): v for k, v in r.items()} for r in rows]
    key = next((k for k in rows[0] if "mAP50-95" in k), None) if rows else None
    if not key:
        return None, len(rows) or None
    best = max(rows, key=lambda r: float(r[key] or 0))
    return int(float(best.get("epoch", 0))), len(rows)


if __name__ == "__main__":
    main()
