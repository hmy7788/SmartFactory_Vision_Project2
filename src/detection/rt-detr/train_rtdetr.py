"""
train_rtdetr.py

RT-DETR(ultralytics) 학습 스크립트 (experiment/rt-detr 브랜치 전용).
CLAUDE.md 3-1의 "RT-DETR도 비교 후보로 고려 가능"에 따른 실험.

⚠️ RT-DETR은 OBB를 지원하지 않아 AABB로 학습한다
   (prepare_rtdetr_dataset.py가 기존 OBB 라벨을 AABB로 변환해 둔 데이터 사용).

⚠️ ultralytics 기본 진행바(tqdm)는 출력을 파일로 리다이렉션하거나 백그라운드로
   돌릴 때 갱신이 안 보이는 경우가 많다 (캐리지리턴 기반이라 버퍼링에 걸림).
   그래서 콜백을 등록해 epoch마다 명시적으로 print(..., flush=True)로 진행상황을 남긴다.

사용법:
    python src/detection/rt-detr/train_rtdetr.py --data datasets/rtdetr_iconic/data.yaml --epochs 50
    (빠른 동작 확인만 하려면 --epochs 3 정도로)
"""

import argparse
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_PROJECT = str(REPO_ROOT / "runs" / "rtdetr")
# ⚠️ project를 상대경로("runs/rtdetr")로 주면 ultralytics가 자체 runs_dir 설정과 합쳐서
#    runs/detect/runs/rtdetr 처럼 이상하게 중첩된다. 그래서 절대경로로 고정한다.
from ultralytics import RTDETR


def register_progress_callbacks(model, total_epochs: int):
    state = {"start": None}

    def on_train_start(trainer):
        state["start"] = time.time()
        print(f"[RT-DETR] 학습 시작 — 총 {total_epochs} epoch", flush=True)

    def on_train_epoch_start(trainer):
        print(f"[RT-DETR] Epoch {trainer.epoch + 1}/{total_epochs} 시작...", flush=True)

    def on_train_epoch_end(trainer):
        elapsed = time.time() - state["start"] if state["start"] else 0
        loss_items = getattr(trainer, "loss_items", None)
        if loss_items is None:
            loss_str = ""
        elif hasattr(loss_items, "tolist"):
            loss_str = f", loss={loss_items.tolist()}"
        else:
            loss_str = f", loss={loss_items}"
        print(f"[RT-DETR] Epoch {trainer.epoch + 1}/{total_epochs} 완료 "
              f"(경과 {elapsed:.1f}s{loss_str})", flush=True)

    def on_fit_epoch_end(trainer):
        metrics = getattr(trainer, "metrics", None)
        if metrics:
            parts = []
            for k, v in metrics.items():
                try:
                    parts.append(f"{k}={float(v):.4f}")
                except (TypeError, ValueError):
                    continue
            if parts:
                shown_epoch = min(trainer.epoch + 1, total_epochs)
                print(f"[RT-DETR] Epoch {shown_epoch}/{total_epochs} 검증 결과: {', '.join(parts)}", flush=True)

    def on_train_end(trainer):
        elapsed = time.time() - state["start"] if state["start"] else 0
        print(f"[RT-DETR] 학습 종료 — 총 소요 {elapsed / 60:.1f}분, "
              f"결과 저장 위치: {trainer.save_dir}", flush=True)

    model.add_callback("on_train_start", on_train_start)
    model.add_callback("on_train_epoch_start", on_train_epoch_start)
    model.add_callback("on_train_epoch_end", on_train_epoch_end)
    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_end", on_train_end)


def main():
    parser = argparse.ArgumentParser(description="RT-DETR 학습 (실험용)")
    parser.add_argument("--data", default="datasets/rtdetr_iconic/data.yaml")
    parser.add_argument("--model", default="checkpoints/rtdetr-l.pt",
                         help="사전학습 체크포인트 경로. 기본은 checkpoints/rtdetr-l.pt "
                              "(없으면 ultralytics가 자동 다운로드하되, 새 이름을 주면 리포 루트에 받으니 "
                              "받은 뒤 checkpoints/로 옮기는 걸 권장)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default=0, help="GPU 인덱스, CPU면 'cpu'")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--name", default="exp")
    args = parser.parse_args()

    print(f"[RT-DETR] 모델 로드: {args.model}", flush=True)
    model = RTDETR(args.model)
    register_progress_callbacks(model, args.epochs)

    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
    )


if __name__ == "__main__":
    main()
