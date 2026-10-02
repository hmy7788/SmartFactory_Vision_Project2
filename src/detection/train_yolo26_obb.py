"""YOLO26n-OBB 부품 검출 모델 학습 / 평가 (YOLO11n-OBB 트랙은 src/detection/yolo11/train_yolo_obb.py)

runs/train/yolo26_obb_parts/args.yaml (2026-09-23 학습, epochs 50) 과 같은 설정으로 학습한다.
Ultralytics 기본값과 다른 값만 TRAIN_CFG 에 적었고, 나머지(증강 hsv·mosaic·translate·scale 등,
optimizer=auto → AdamW lr≈0.0011, lr0/lrf, warmup)는 기본값 그대로다.

데이터: data/data_final/obb/data.yaml
  - train: images/train (831장) · val: images/test (149장)
  - val 키에 test 폴더를 넣었다 (Train/Test 2분할, 별도 val 없음)
  - 클래스 5종: bolt_2, bolt_1, mother_part, part_3hole, part_2hole

실행 (저장소 루트에서, conda activate vision_project 후):
  python -m src.detection.yolo26.train_yolo26_obb                    # 학습 → test 평가 → 가중치 복사
  python -m src.detection.yolo26.train_yolo26_obb --device cpu       # GPU 없을 때
  python -m src.detection.yolo26.train_yolo26_obb --test-only --weights weights/yolo26_obb_parts_50.pt
  python -m src.detection.yolo26.train_yolo26_obb --model yolo11n-obb.pt --name yolo11_obb_parts --epochs 100 --batch 8

결과:
  runs/train/<name>/            학습 곡선 · confusion matrix · weights/best.pt
  weights/<name>_e<epochs>.pt   best.pt 복사본 (이미 있으면 덮어쓰지 않음, --overwrite 로 허용)
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # src/detection/yolo26/ → 저장소 루트
DATA_YAML = ROOT / "data" / "data_final" / "obb" / "data.yaml"
RUNS_DIR = ROOT / "runs" / "train"
WEIGHTS_DIR = ROOT / "weights"                         # 저장소 규칙: 모든 .pt 는 weights/ (weights/README.md)

# args.yaml 에서 Ultralytics 기본값과 달랐던 값
TRAIN_CFG = dict(
    task="obb",
    imgsz=640,
    epochs=50,
    batch=16,
    patience=25,       # 25 에폭 동안 개선이 없으면 조기 종료
    workers=4,
    degrees=180,       # OBB: 어느 각도로 놓여도 인식하도록 ±180° 회전 증강
    flipud=0.5,        # 위에서 내려다본 촬영이라 상하 반전도 허용
    seed=0,
    deterministic=True,
    exist_ok=True,
    plots=True,
)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="yolo26n-obb.pt", help="사전학습 가중치 (DOTAv1 OBB). 처음 실행 시 자동 다운로드")
    p.add_argument("--data", type=Path, default=DATA_YAML)
    p.add_argument("--name", default="yolo26_obb_parts", help="runs/train/ 아래 결과 폴더 이름")
    p.add_argument("--epochs", type=int, default=TRAIN_CFG["epochs"])
    p.add_argument("--batch", type=int, default=TRAIN_CFG["batch"])
    p.add_argument("--imgsz", type=int, default=TRAIN_CFG["imgsz"])
    p.add_argument("--device", default="0", help="GPU 번호(0) 또는 cpu")
    p.add_argument("--test-only", action="store_true", help="학습 없이 --weights 로 test 평가만")
    p.add_argument("--weights", type=Path, default=None, help="--test-only 때 평가할 가중치")
    p.add_argument("--overwrite", action="store_true", help="weights/ 의 같은 이름 가중치를 덮어쓰기")
    return p.parse_args()


def check_data(data_yaml: Path):
    if not data_yaml.exists():
        sys.exit(f"data.yaml 없음: {data_yaml}")
    import yaml
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    base = Path(cfg.get("path") or data_yaml.parent)
    if not base.is_absolute():
        base = data_yaml.parent / base
    if not base.exists():                       # data.yaml 의 절대경로가 다른 PC 경로면 yaml 옆 폴더로
        base = data_yaml.parent
    for split in ("train", "val"):
        folder = base / cfg[split]
        n = sum(1 for f in folder.glob("*") if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}) if folder.exists() else 0
        print(f"  {split:5s}: {folder}  ({n}장)")
        if n == 0:
            sys.exit(f"{split} 이미지가 없습니다: {folder}")
    print(f"  클래스 {cfg.get('nc')}종: {list(cfg.get('names', {}).values())}")


def evaluate(weights: Path, args):
    from ultralytics import YOLO
    print(f"\n[평가] {weights}  (data.yaml 의 val = test 149장)")
    metrics = YOLO(str(weights)).val(data=str(args.data), imgsz=args.imgsz, batch=args.batch,
                                     device=args.device, plots=True, project=str(RUNS_DIR),
                                     name=f"{args.name}_test", exist_ok=True)
    box = metrics.box
    print(f"  Precision {box.mp:.3f} | Recall {box.mr:.3f} | mAP50 {box.map50:.3f} | mAP50-95 {box.map:.3f}")
    for i, name in metrics.names.items():
        if i < len(box.ap50):
            print(f"    {name:12s} AP50 {box.ap50[i]:.3f}  AP50-95 {box.ap[i]:.3f}")
    print(f"  추론 속도(이미지 1장): {metrics.speed}")
    return metrics


def train(args):
    from ultralytics import YOLO
    print("[데이터 확인]")
    check_data(args.data)
    cfg = dict(TRAIN_CFG, data=str(args.data), epochs=args.epochs, batch=args.batch, imgsz=args.imgsz,
               device=args.device, project=str(RUNS_DIR), name=args.name)
    print(f"\n[학습] {args.model}  epochs {args.epochs} · batch {args.batch} · imgsz {args.imgsz} · device {args.device}")
    model = YOLO(args.model)
    model.train(**cfg)

    best = Path(model.trainer.best)
    if not best.exists():
        sys.exit(f"best.pt 를 찾지 못했습니다: {best}")
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    out = WEIGHTS_DIR / f"{args.name}_e{args.epochs}.pt"
    if out.exists() and not args.overwrite:
        print(f"\n{out} 이(가) 이미 있어 복사하지 않았습니다 (--overwrite 로 덮어쓰기). 새 가중치: {best}")
    else:
        shutil.copy2(best, out)
        print(f"\n가중치 저장: {out}")
    evaluate(best, args)


def main():
    args = parse_args()
    if args.test_only:
        if not args.weights or not args.weights.exists():
            sys.exit("--test-only 에는 존재하는 --weights 가 필요합니다")
        evaluate(args.weights, args)
    else:
        train(args)


if __name__ == "__main__":
    main()
