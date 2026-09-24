"""
capture_hole_check.py

live_hole_check.py와 동일한 화면(Result/Debug)을 띄우되, 's' 키를 누르면 그 순간의
Result/Debug 화면을 발표 자료용 사진으로 저장한다. 'q'는 종료.

사용법:
    python src/rule_based/capture_hole_check.py --camera 3 --exposure 1/20
    python src/rule_based/capture_hole_check.py --camera 3 --output runs/presentation_shots --tag before
"""

import argparse
import sys
import time
from collections import Counter, deque
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "detection"))
from hole_count_check import classify_model, _draw_debug  # noqa: E402
from camera_utils import remove_droidcam_watermark  # noqa: E402

DEBOUNCE_FRAMES = 7
DEBOUNCE_MIN_RATIO = 0.6


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="룰베이스 판정 화면을 's'키로 캡처해서 저장")
    parser.add_argument("--camera", type=int, default=0, help="cv2.VideoCapture 인덱스")
    parser.add_argument("--backend", choices=["dshow", "msmf"], default="dshow",
                         help="카메라 백엔드. DroidCam 가상 웹캠은 msmf로만 잡히는 경우가 있음(실측)")
    parser.add_argument("--droidcam-watermark", action="store_true",
                         help="DroidCam 무료 버전 'using droidcam.app' 워터마크 영역을 지우고 판정 (640x480 기준 실측 위치)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--exposure", default=None, help="예: '1/20' (초 단위, 셔터 속도 수동 고정)")
    parser.add_argument("--output", default="runs/hole_check_capture", help="저장 폴더")
    parser.add_argument("--tag", default="", help="파일명 앞에 붙일 태그 (예: before/after)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if args.exposure:
        seconds = float(Fraction(args.exposure))
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, float(np.log2(seconds)))

    if not cap.isOpened():
        print(f"[CAPTURE] 카메라(index={args.camera})를 열 수 없습니다.", flush=True)
        return

    print(f"[CAPTURE] 저장 폴더: {output_dir}", flush=True)
    print("[CAPTURE] 's'를 누르면 지금 화면을 저장, 'q'를 누르면 종료합니다.", flush=True)

    history = deque(maxlen=DEBOUNCE_FRAMES)
    saved_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[CAPTURE] 프레임을 읽지 못했습니다.", flush=True)
            break

        if args.droidcam_watermark:
            frame = remove_droidcam_watermark(frame)

        model, message, analysis = classify_model(frame)
        history.append(model)

        counts = Counter(history)
        stable_model, stable_count = counts.most_common(1)[0]
        confirmed = stable_model if stable_count >= max(1, len(history)) * DEBOUNCE_MIN_RATIO else None

        annotated = frame.copy()
        result_color = (0, 255, 0) if confirmed else (0, 0, 255)
        cv2.putText(annotated, f"result: {confirmed or 'NG/판정중'}", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, result_color, 2)
        cv2.putText(annotated, f"frame: {model or 'NG'}  rotation={analysis['rotation_deg']:.1f}deg",
                    (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(annotated, message, (10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(annotated, f"저장됨: {saved_count}장 ('s'로 저장, 'q'로 종료)", (10, annotated.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        debug_view = _draw_debug(frame, analysis)

        cv2.imshow("Result (s: save, q: quit)", annotated)
        cv2.imshow("Debug (rule-based evidence)", debug_view)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            ts = time.strftime("%Y%m%d_%H%M%S")
            prefix = f"{args.tag}_{ts}" if args.tag else ts
            result_path = output_dir / f"{prefix}_result.png"
            debug_path = output_dir / f"{prefix}_debug.png"
            cv2.imwrite(str(result_path), annotated)
            cv2.imwrite(str(debug_path), debug_view)
            saved_count += 1
            print(f"[CAPTURE] 저장: {result_path.name}, {debug_path.name} (결과: {confirmed or 'NG'})", flush=True)

    cap.release()
    cv2.destroyAllWindows()
    print(f"[CAPTURE] 종료 — 총 {saved_count}장 저장됨 -> {output_dir}", flush=True)


if __name__ == "__main__":
    main()
