# src/detection/realtime_inference.py
# ──────────────────────────────────────────────
# YOLO OBB 실시간 추론 (웹캠)
#
# 사용:
#   python src/detection/realtime_inference.py
#   python src/detection/realtime_inference.py --weights checkpoints/yolo_obb_parts.pt
#   python src/detection/realtime_inference.py --source data/dataset/images/test  # 폴더
#
# 단축키:
#   q / ESC  → 종료
#   s        → 현재 프레임 저장 (runs/snapshots/)
#   p        → 일시정지
# ──────────────────────────────────────────────
import argparse
import time
from pathlib import Path

import cv2
import numpy as np

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_WEIGHTS = str(PROJECT_ROOT / "checkpoints" / "yolo_obb_parts.pt")
SNAPSHOT_DIR    = PROJECT_ROOT / "runs" / "snapshots"

# 클래스별 색상 (BGR)
CLASS_COLORS = {
    "볼트_주황": (0,  140, 255),   # 주황
    "볼트_노랑": (0,  230, 230),   # 노랑
    "나무_5구멍": (0,  200,  80),  # 녹색
    "나무_3구멍": (80, 180, 255),  # 하늘색
    "나무_2구멍": (200, 80, 255),  # 보라
}
DEFAULT_COLOR = (200, 200, 200)

# FPS 계산용
FPS_AVG_N = 30


def parse_args():
    p = argparse.ArgumentParser(description="YOLO OBB 실시간 추론")
    p.add_argument("--weights", default=DEFAULT_WEIGHTS, help="모델 가중치 경로")
    p.add_argument("--source",  default="0",
                   help="입력 소스: 0 (웹캠) / 영상 파일 경로 / 이미지 폴더 경로")
    p.add_argument("--conf",    type=float, default=0.45, help="신뢰도 임계값")
    p.add_argument("--imgsz",   type=int,   default=640)
    p.add_argument("--device",  default="0", help="GPU 인덱스 또는 'cpu'")
    p.add_argument("--width",   type=int,   default=1280, help="웹캠 해상도 가로")
    p.add_argument("--height",  type=int,   default=720,  help="웹캠 해상도 세로")
    p.add_argument("--no-window", action="store_true",
                   help="화면 출력 없이 MJPEG 서버만 (파이프라인 연동용)")
    return p.parse_args()


# ── OBB 시각화 ────────────────────────────────

def draw_obb_results(frame: np.ndarray, results, names: dict) -> np.ndarray:
    """YOLO OBB 결과를 프레임에 그려 반환."""
    vis = frame.copy()

    if results is None or results[0].obb is None:
        return vis

    obb_data = results[0].obb
    if len(obb_data) == 0:
        return vis

    # xyxyxyxy: shape (N, 4, 2) — 4개 꼭짓점 (x, y)
    corners_all = obb_data.xyxyxyxy.cpu().numpy()  # (N, 4, 2)
    cls_ids     = obb_data.cls.cpu().numpy().astype(int)
    confs       = obb_data.conf.cpu().numpy()

    for corners, cls_id, conf in zip(corners_all, cls_ids, confs):
        cls_name = names.get(cls_id, str(cls_id))
        color    = CLASS_COLORS.get(cls_name, DEFAULT_COLOR)

        # 폴리곤 그리기
        pts = corners.astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(vis, [pts], isClosed=True, color=color, thickness=2)

        # 레이블 배경 + 텍스트
        label = f"{cls_name}  {conf:.2f}"
        x0, y0 = int(corners[0, 0]), int(corners[0, 1])
        (tw, th), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
        )
        # 텍스트 위치가 화면 위를 넘어가면 아래쪽에 표시
        ty = y0 - 6 if y0 - th - 6 > 0 else y0 + th + 6
        cv2.rectangle(vis,
                      (x0, ty - th - 4), (x0 + tw + 6, ty + baseline),
                      color, -1)
        cv2.putText(vis, label,
                    (x0 + 3, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 0), 1, cv2.LINE_AA)

    return vis


def draw_hud(
    frame: np.ndarray,
    fps: float,
    n_detected: int,
    class_counts: dict,
    paused: bool,
) -> np.ndarray:
    """상단 HUD 오버레이."""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 52), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    # FPS
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (180, 255, 180), 2)
    # 감지 개수
    cv2.putText(frame, f"감지: {n_detected}개", (110, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 220, 220), 2)
    # 클래스별 카운트
    x_pos = 240
    for cls_name, cnt in class_counts.items():
        color = CLASS_COLORS.get(cls_name, DEFAULT_COLOR)
        txt = f"{cls_name}:{cnt}"
        cv2.putText(frame, txt, (x_pos, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        (tw, _), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        x_pos += tw + 14
    # 단축키 안내
    hint = "[q/ESC] 종료   [s] 저장   [p] 일시정지"
    if paused:
        hint = "⏸ 일시정지 중   [p] 재개"
    cv2.putText(frame, hint, (10, 46),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 120), 1)

    return frame


# ── 메인 루프 ────────────────────────────────

def run(args):
    # 모델 로드
    try:
        from ultralytics import YOLO
    except ImportError:
        print("❌ ultralytics 미설치. conda env `vision_programming` 활성화 후 실행.")
        return

    weights = Path(args.weights)
    if not weights.exists():
        print(f"❌ 가중치 없음: {weights}")
        print("   먼저 학습: python src/detection/train_yolo_obb.py")
        return

    print(f"[Inference] 모델 로드: {weights}")
    model = YOLO(str(weights))
    names: dict = model.names   # {0: "볼트_주황", ...}

    # 소스 열기
    source = args.source
    is_webcam = source.isdigit()
    if is_webcam:
        cap = cv2.VideoCapture(int(source))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        print(f"[Inference] 웹캠 #{source} 열기  ({args.width}x{args.height})")
    else:
        src_path = Path(source)
        if src_path.is_dir():
            # 이미지 폴더 모드
            _run_folder(model, src_path, args, names)
            return
        cap = cv2.VideoCapture(str(src_path))
        print(f"[Inference] 영상 파일: {src_path}")

    # FPS 추적
    fps_deque: list[float] = []
    prev_time = time.perf_counter()
    paused = False
    snapshot_idx = 0
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    print("[Inference] 시작  (q/ESC 종료, s 저장, p 일시정지)")

    while cap.isOpened():
        if not paused:
            ret, frame = cap.read()
            if not ret:
                break

            # 추론
            results = model.predict(
                frame,
                conf   = args.conf,
                imgsz  = args.imgsz,
                device = args.device,
                verbose= False,
            )

            # 클래스별 카운트
            class_counts: dict[str, int] = {}
            n_det = 0
            if results[0].obb is not None and len(results[0].obb):
                for cls_id in results[0].obb.cls.cpu().numpy().astype(int):
                    cls_name = names.get(cls_id, str(cls_id))
                    class_counts[cls_name] = class_counts.get(cls_name, 0) + 1
                n_det = int(results[0].obb.cls.shape[0])

            # 시각화
            vis = draw_obb_results(frame, results, names)

            # FPS
            now = time.perf_counter()
            fps_deque.append(1.0 / max(now - prev_time, 1e-6))
            prev_time = now
            if len(fps_deque) > FPS_AVG_N:
                fps_deque.pop(0)
            fps = sum(fps_deque) / len(fps_deque)

            vis = draw_hud(vis, fps, n_det, class_counts, paused)

        if not args.no_window:
            cv2.imshow("YOLO OBB — 실시간 추론", vis)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):   # q / ESC
                break
            elif key == ord("s"):       # 저장
                snap_path = SNAPSHOT_DIR / f"snap_{snapshot_idx:04d}.jpg"
                cv2.imwrite(str(snap_path), vis)
                print(f"[Inference] 저장: {snap_path}")
                snapshot_idx += 1
            elif key == ord("p"):       # 일시정지
                paused = not paused
        else:
            # no-window 모드: 파이프라인에 JPEG 바이트 공급 가능하도록 대기
            time.sleep(1 / 30)

    cap.release()
    if not args.no_window:
        cv2.destroyAllWindows()
    print("[Inference] 종료")


def _run_folder(model, folder: Path, args, names: dict):
    """이미지 폴더 일괄 추론 + 결과 저장."""
    img_paths = sorted(list(folder.glob("*.jpg")) + list(folder.glob("*.png")))
    if not img_paths:
        print(f"❌ 이미지 없음: {folder}")
        return

    out_dir = folder.parent.parent / "runs" / "obb_infer" / folder.name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Inference] 폴더 모드: {len(img_paths)}장  →  {out_dir}")

    for img_path in img_paths:
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
        results = model.predict(
            frame, conf=args.conf, imgsz=args.imgsz,
            device=args.device, verbose=False
        )
        vis = draw_obb_results(frame, results, names)
        cv2.imwrite(str(out_dir / img_path.name), vis)

    print(f"[Inference] 완료: {out_dir}")


if __name__ == "__main__":
    args = parse_args()
    run(args)
