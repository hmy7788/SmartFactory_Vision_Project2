"""
live_hole_check.py

웹캠으로 hole_count_check.py의 룰베이스(구멍 위치 + 볼트 색상) Model A/B/C 분류를
실시간으로 테스트한다. 'q' 누르면 종료.

⚠️ CLAUDE.md 기준 정식 환경은 Logitech C270, TOP-DOWN, 검은 배경, 오토포커스 OFF다.
   또한 이 룰베이스는 "완성된 조립체" 사진 기준으로 만들어졌다 — 손이 가려져 있거나
   조립 중인 상태에서는 정확도가 떨어질 수 있다 (완성 후 카메라 앞에 놓고 테스트할 것).

⚠️ 창이 두 개 뜬다:
   1) "Result" — 항상 원본(회전 안 한) 카메라 프레임만 보여준다. hole_count_check.py가
      내부적으로 mother_part를 수평으로 되돌리는 회전 보정을 하는데(캔버스 크기가 매
      프레임 조금씩 다르게 확장됨), 그 회전된 화면을 그대로 띄우면 손이 살짝만 움직여도
      화면이 매 프레임 확 튀어 보인다(실제로 그렇게 보고받음) — 그래서 이 창은 항상
      안정적인 원본 위에 최종 결과 텍스트만 얹는다. 최근 몇 프레임의 다수결로 결과를
      안정화한다(디바운스) — CLAUDE.md의 "조립 섹션 실시간 검증" 디바운스와 같은 이유.
   2) "Debug" — hole_count_check.py의 판단 근거를 그대로 시각화한다(회전 보정된 화면
      기준, 매 프레임 흔들릴 수 있음 — 진단용이라 괜찮음): 외곽선, 빈 구멍, mother_part
      밴드 경계선, 그리고 각 접합점에서 실제로 샘플링한 범위(자홍색 원)와 그 안에서 읽은
      hue 값·채도 비율·판정 색상까지 숫자로 보여준다. 색상 오판정이 나면 이 창에서
      hue 값이 얼마로 찍히는지 보고 HSV_RANGES 경계를 다시 맞추면 된다.

⚠️ 노출: C270 자동노출이 배경을 회색으로 띄우는 경우가 실측 확인됐다(밝기 90~110대,
   검은 배경이면 나와야 할 0~20대가 아니었음) — 자동노출이 밝은 흰/원목색 부품 기준으로
   전체 프레임을 밝게 보정해버리는 것으로 보인다. --exposure로 셔터 속도를 수동
   고정하면(예: 1/20초) 훨씬 어둡게(검은 배경에 가깝게) 나온다 — 실측으로 확인됨.

사용법:
    python src/rule_based/live_hole_check.py --camera 0
    python src/rule_based/live_hole_check.py --camera 3 --exposure 1/20
"""

import argparse
import sys
from collections import Counter, deque
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "detection"))
from hole_count_check import classify_model, _draw_debug  # noqa: E402
from camera_utils import remove_droidcam_watermark  # noqa: E402

DEBOUNCE_FRAMES = 7       # 이 프레임 수만큼 최근 기록을 보고 다수결
DEBOUNCE_MIN_RATIO = 0.6  # 그 중 이 비율 이상 같은 결과여야 화면에 확정 표시


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="룰베이스(구멍 위치) Model A/B/C 분류 웹캠 실시간 테스트")
    parser.add_argument("--camera", type=int, default=0, help="cv2.VideoCapture 인덱스")
    parser.add_argument("--backend", choices=["dshow", "msmf"], default="dshow",
                         help="카메라 백엔드. DroidCam 가상 웹캠은 msmf로만 잡히는 경우가 있음(실측)")
    parser.add_argument("--droidcam-watermark", action="store_true",
                         help="DroidCam 무료 버전 'using droidcam.app' 워터마크 영역을 지우고 판정 (640x480 기준 실측 위치)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--exposure", default=None,
                         help="셔터 속도를 수동 고정 (예: '1/20' 또는 '0.05', 초 단위). "
                              "생략하면 카메라 자동노출을 그대로 씀 (배경이 회색으로 뜨면 이 옵션을 써볼 것)")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)

    if args.exposure:
        seconds = float(Fraction(args.exposure))
        # DirectShow 관례: CAP_PROP_EXPOSURE 값은 log2(초) — 예: 1/20초 -> log2(1/20) ≈ -4.32
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 0.25=수동, 0.75=자동 (DirectShow 관례)
        cap.set(cv2.CAP_PROP_EXPOSURE, float(np.log2(seconds)))

    if not cap.isOpened():
        print(f"[LIVE] 카메라(index={args.camera})를 열 수 없습니다.", flush=True)
        return

    if args.exposure:
        print(f"[LIVE] 수동 노출 적용: 요청 {args.exposure}초, 실제 AUTO_EXPOSURE={cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)}, "
              f"EXPOSURE={cap.get(cv2.CAP_PROP_EXPOSURE)}", flush=True)

    print("[LIVE] 시작 — 완성된 조립체를 카메라 앞에 놓아보세요. 'q'를 누르면 종료합니다.", flush=True)

    history = deque(maxlen=DEBOUNCE_FRAMES)
    while True:
        ret, frame = cap.read()
        if not ret:
            print("[LIVE] 프레임을 읽지 못했습니다.", flush=True)
            break

        if args.droidcam_watermark:
            frame = remove_droidcam_watermark(frame)

        model, message, analysis = classify_model(frame)
        history.append(model)

        # 최근 프레임들의 다수결로 화면에 보여줄 결과를 안정화 (디바운스)
        counts = Counter(history)
        stable_model, stable_count = counts.most_common(1)[0]
        confirmed = stable_model if stable_count >= max(1, len(history)) * DEBOUNCE_MIN_RATIO else None

        annotated = frame.copy()  # ⚠️ 회전 보정된 내부 작업 이미지가 아니라 항상 원본 프레임에만 그린다
        result_color = (0, 255, 0) if confirmed else (0, 0, 255)
        cv2.putText(annotated, f"result: {confirmed or 'NG/판정중'}", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, result_color, 2)
        cv2.putText(annotated, f"frame: {model or 'NG'}  rotation={analysis['rotation_deg']:.1f}deg",
                    (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(annotated, message, (10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        debug_view = _draw_debug(frame, analysis)

        cv2.imshow("Result (q: quit)", annotated)
        cv2.imshow("Debug (rule-based evidence)", debug_view)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[LIVE] 종료", flush=True)


if __name__ == "__main__":
    main()
