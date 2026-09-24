"""
live_test.py

웹캠으로 RT-DETR 체크포인트를 실시간 테스트한다 (experiment/rt-detr 브랜치 전용).
창에 박스+클래스+confidence가 실시간으로 그려진다. 'q' 누르면 종료.

⚠️ CLAUDE.md 기준 정식 환경은 Logitech C270, TOP-DOWN, 검은 배경, 오토포커스 OFF다.
   그 조건이 아닌 카메라/각도/배경으로 테스트하면 정확도가 실제보다 낮게 나올 수 있다
   (학습 데이터와 도메인이 다르기 때문 — 파이프라인 동작 확인용으로만 쓸 것).

사용법:
    python src/detection/rt-detr/live_test.py --camera 0
    python src/detection/rt-detr/live_test.py --camera 0 --weights runs/rtdetr/main_run/weights/last.pt
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
from ultralytics import RTDETR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src/detection
from camera_utils import remove_droidcam_watermark  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="RT-DETR 웹캠 실시간 테스트")
    parser.add_argument("--camera", type=int, default=0, help="cv2.VideoCapture 인덱스")
    parser.add_argument("--backend", choices=["dshow", "msmf"], default="dshow",
                         help="카메라 백엔드. DroidCam 가상 웹캠은 msmf로만 잡히는 경우가 있음(실측)")
    parser.add_argument(
        "--weights",
        default="runs/rtdetr/full_run/weights/best.pt",
        help="학습된 RT-DETR 가중치 경로",
    )
    parser.add_argument("--conf", type=float, default=0.25, help="confidence threshold")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--target-fps", type=int, default=30, help="카메라에 요청할 목표 fps")
    parser.add_argument("--droidcam-watermark", action="store_true",
                         help="DroidCam 무료 버전 'using droidcam.app' 워터마크 영역을 지우고 추론 (640x480 기준 실측 위치)")
    args = parser.parse_args()

    print(f"[LIVE] 모델 로드: {args.weights}", flush=True)
    model = RTDETR(args.weights)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW)
    # ⚠️ C270은 기본 압축 안 된 YUY2 포맷으로는 1280x720에서 USB 대역폭 한계로 ~10fps로
    # 묶인다. MJPG(압축) 포맷을 명시적으로 요청해야 720p에서 30fps가 나온다.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.target_fps)

    if not cap.isOpened():
        print(f"[LIVE] 카메라(index={args.camera})를 열 수 없습니다.", flush=True)
        return

    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join(chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4))
    print(f"[LIVE] 카메라 설정: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
          f"@ {cap.get(cv2.CAP_PROP_FPS):.0f}fps (FOURCC={fourcc_str})", flush=True)

    print("[LIVE] 시작 — 'q'를 누르면 종료합니다.", flush=True)

    prev_time = time.time()
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[LIVE] 프레임을 읽지 못했습니다.", flush=True)
            break

        if args.droidcam_watermark:
            frame = remove_droidcam_watermark(frame)

        results = model.predict(frame, conf=args.conf, verbose=False)
        annotated = results[0].plot().copy()  # plot()은 읽기 전용 배열을 반환 — putText 전에 복사 필요

        now = time.time()
        fps = 1.0 / max(now - prev_time, 1e-6)
        prev_time = now
        cv2.putText(annotated, f"FPS: {fps:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        cv2.imshow("RT-DETR Live Test (q: quit)", annotated)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[LIVE] 종료", flush=True)


if __name__ == "__main__":
    main()
