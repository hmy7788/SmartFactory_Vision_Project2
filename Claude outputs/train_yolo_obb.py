# src/detection/train_yolo_obb.py
# ──────────────────────────────────────────────
# YOLO OBB (Oriented Bounding Box) 학습 스크립트
#
# 사전 준비:
#   1. conda activate vision_programming
#   2. python src/detection/prepare_dataset.py   ← 데이터셋 분할 먼저
#
# 학습:
#   python src/detection/train_yolo_obb.py
#   python src/detection/train_yolo_obb.py --model yolo11n-obb.pt --epochs 150
#
# 테스트(학습 후):
#   python src/detection/train_yolo_obb.py --test-only
# ──────────────────────────────────────────────
import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_YAML    = PROJECT_ROOT / "data" / "data.yaml"
CKPT_DIR     = PROJECT_ROOT / "checkpoints"
BEST_PT_OUT  = CKPT_DIR / "yolo_obb_parts.pt"

# ── 기본 학습 설정 ────────────────────────────
TRAIN_CFG = dict(
    task    = "obb",            # ← OBB 핵심
    data    = str(DATA_YAML),
    imgsz   = 640,
    epochs  = 100,
    batch   = 16,
    patience= 20,               # Early stopping
    device  = "0",              # GPU; CPU는 "cpu"
    project = str(CKPT_DIR),
    name    = "yolo_obb_parts",
    exist_ok= True,
    # ── 증강 (검은 배경 + TOP-DOWN 고정) ──
    hsv_h   = 0.010,            # 색조 변화 최소화
    hsv_s   = 0.30,
    hsv_v   = 0.25,
    fliplr  = 0.5,
    flipud  = 0.0,              # 위아래 반전 OFF (TOP-DOWN 고정)
    degrees = 180.0,            # OBB는 회전 학습이 핵심 — 넓게 허용
    mosaic  = 0.3,
    copy_paste = 0.2,
    # ── 로깅 ──
    plots   = True,
    save    = True,
    verbose = True,
)


def parse_args():
    p = argparse.ArgumentParser(description="YOLO OBB 학습/테스트")
    p.add_argument("--model",  default="yolov8n-obb.pt",
                   help="베이스 모델 (yolov8n-obb.pt / yolo11n-obb.pt 등)")
    p.add_argument("--epochs", type=int,   default=TRAIN_CFG["epochs"])
    p.add_argument("--batch",  type=int,   default=TRAIN_CFG["batch"])
    p.add_argument("--imgsz",  type=int,   default=TRAIN_CFG["imgsz"])
    p.add_argument("--device", default=TRAIN_CFG["device"])
    p.add_argument("--test-only", action="store_true",
                   help="학습 없이 저장된 모델로 테스트만 실행")
    p.add_argument("--weights", default=str(BEST_PT_OUT),
                   help="--test-only 시 사용할 가중치 경로")
    return p.parse_args()


def check_data_yaml():
    if not DATA_YAML.exists():
        print(f"❌ data.yaml 없음: {DATA_YAML}")
        print("   먼저 실행하세요: python src/detection/prepare_dataset.py")
        sys.exit(1)
    dataset_dir = DATA_YAML.parent / "dataset"
    for split in ("train", "val", "test"):
        img_dir = dataset_dir / "images" / split
        if not img_dir.exists() or not list(img_dir.glob("*.jpg")):
            print(f"❌ {split} 이미지 없음: {img_dir}")
            print("   python src/detection/prepare_dataset.py 를 먼저 실행하세요.")
            sys.exit(1)
    print(f"✅ data.yaml 확인: {DATA_YAML}")


def train(args):
    try:
        from ultralytics import YOLO
    except ImportError:
        print("❌ ultralytics 미설치. conda env `vision_programming` 활성화 후 실행.")
        sys.exit(1)

    check_data_yaml()
    CKPT_DIR.mkdir(parents=True, exist_ok=True)

    cfg = dict(TRAIN_CFG)
    cfg.update(dict(
        epochs = args.epochs,
        batch  = args.batch,
        imgsz  = args.imgsz,
        device = args.device,
    ))

    print(f"\n[YOLO OBB] 학습 시작")
    print(f"  베이스 모델: {args.model}")
    print(f"  에폭: {cfg['epochs']}  배치: {cfg['batch']}  imgsz: {cfg['imgsz']}")
    print(f"  디바이스: {cfg['device']}\n")

    model = YOLO(args.model)
    results = model.train(**cfg)

    # best.pt 복사
    best_src = CKPT_DIR / "yolo_obb_parts" / "weights" / "best.pt"
    if best_src.exists():
        shutil.copy2(best_src, BEST_PT_OUT)
        print(f"\n✅ 최적 가중치 저장: {BEST_PT_OUT}")

    # 바로 테스트
    _run_test(args.weights if Path(args.weights).exists() else str(BEST_PT_OUT), args)
    return results


def _run_test(weights: str, args):
    from ultralytics import YOLO
    print(f"\n[YOLO OBB] 테스트 세트 평가")
    print(f"  가중치: {weights}")
    model = YOLO(weights)
    metrics = model.val(
        data   = str(DATA_YAML),
        split  = "test",          # test 세트로 평가
        imgsz  = args.imgsz,
        device = args.device,
        plots  = True,
        save_json = True,
    )
    print("\n[결과]")
    # OBB metrics: mAP50, mAP50-95
    try:
        print(f"  mAP@50:    {metrics.box.map50:.4f}")
        print(f"  mAP@50-95: {metrics.box.map:.4f}")
        # 클래스별
        from ultralytics.utils import LOGGER
        for i, cls_name in enumerate(metrics.names.values()):
            ap50 = metrics.box.ap50[i] if i < len(metrics.box.ap50) else float("nan")
            print(f"  {cls_name:12s}  AP50={ap50:.4f}")
    except Exception as e:
        print(f"  (metrics 출력 오류: {e})")


def main():
    args = parse_args()

    if args.test_only:
        if not Path(args.weights).exists():
            print(f"❌ 가중치 없음: {args.weights}")
            sys.exit(1)
        from ultralytics import YOLO  # noqa: F401
        _run_test(args.weights, args)
    else:
        train(args)


if __name__ == "__main__":
    main()
