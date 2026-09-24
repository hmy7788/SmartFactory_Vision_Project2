"""
카메라(또는 영상 파일) -> RT-DETR -> 어댑터 -> InspectionService -> 한글 HUD 라이브 검사.

재료 확인(필요/현재 개수) -> 조립 검사(H1~H5 구멍별 볼트/부품 배치, 오류 원인 안내) 흐름을
RT-DETR 검출로 돌린다. RT-DETR은 회전 없는 박스만 주기 때문에 src/vision/rtdetr_adapter.py가
mother 각도를 영상에서 복원해서 엔진에 넘긴다.

⚠️ 원래 엔진(config/mvp.json)은 (1) mother가 ±15° 넘게 기울면 거부하고 (2) 세로 부품이 mother
   "위쪽"으로만 붙는다고 가정하고 (3) H1을 화면 왼쪽으로 고정해서, 조립체를 다른 방향으로
   놓으면 정상 조립도 실패한다 (정답을 아는 사진 100장 기준 PASS 61장). 기본 설정인
   config/rtdetr_live.json은 이 셋을 풀어서(각도 89.9°, allow_parts_below, allow_mirrored_holes)
   같은 100장에서 PASS 98장이 나온다 (다른 모델 레시피/틀린 구멍 위치 레시피로 검사한
   300건은 PASS 0건). 팀원 원래 동작이 필요하면 --config config/mvp.json.

사용법 (저장소 루트에서):
    python -m scripts.live_inspection --camera 3 --recipe 3
    python -m scripts.live_inspection --camera 1 --backend msmf --droidcam-watermark
    python -m scripts.live_inspection --video 1.mp4 --recipe 3 --save-video runs/inspection_demo.mp4 --no-window

키: [1/2/3] 레시피 선택(초기화)  [n] 새 제품(초기화)  [q] 종료
"""

import argparse
import sys
import time
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from ultralytics import RTDETR

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "detection"))

from camera_utils import remove_droidcam_watermark  # noqa: E402
from src.app.config import load_config  # noqa: E402
from src.app.hud import Hud  # noqa: E402
from src.app.inspection_service import InspectionService  # noqa: E402
from src.process.recipe import load_recipe  # noqa: E402
from src.vision.rtdetr_adapter import RTDETRAdapter  # noqa: E402


def open_camera(args):
    cap = cv2.VideoCapture(args.camera, cv2.CAP_MSMF if args.backend == "msmf" else cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    if args.exposure:
        # DirectShow 관례: CAP_PROP_EXPOSURE는 log2(초). 예: 1/20초 -> 약 -4.32
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, float(np.log2(float(Fraction(args.exposure)))))
    return cap


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="RT-DETR 기반 라이브 조립 검사")
    parser.add_argument("--recipe", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--weights", default=str(ROOT / "runs/rtdetr/full_run/weights/best.pt"))
    parser.add_argument("--conf", type=float, default=None, help="생략하면 config의 confidence_threshold")
    parser.add_argument("--config", type=Path, default=ROOT / "config/rtdetr_live.json",
                        help="기본은 각도 제한을 풀고 위/아래 부품·좌우 뒤집힌 번호를 허용하는 라이브용 설정 "
                             "(팀원 원본은 config/mvp.json)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["dshow", "msmf"], default="dshow",
                        help="DroidCam 가상 웹캠은 msmf로만 잡히는 경우가 있음")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--exposure", default=None, help="셔터 속도 수동 고정(예: '1/20')")
    parser.add_argument("--droidcam-watermark", action="store_true",
                        help="DroidCam 무료 버전 워터마크 영역을 지우고 추론 (640x480 기준)")
    parser.add_argument("--video", type=Path, default=None, help="카메라 대신 영상 파일로 실행")
    parser.add_argument("--save-video", type=Path, default=None, help="HUD가 그려진 결과를 mp4로 저장")
    parser.add_argument("--no-window", action="store_true", help="창 없이 실행 (저장/콘솔 로그만)")
    parser.add_argument("--max-frames", type=int, default=0, help="0이면 끝까지")
    args = parser.parse_args()

    config = load_config(args.config)
    recipes = {n: load_recipe(ROOT / f"config/recipes/recipe_{n}.json") for n in (1, 2, 3)}
    service = InspectionService(config, recipes[args.recipe])
    adapter = RTDETRAdapter()
    hud = Hud(config)
    conf = args.conf if args.conf is not None else config["confidence_threshold"]

    print(f"[INSPECT] 모델 로드: {args.weights}", flush=True)
    model = RTDETR(args.weights)

    is_video = args.video is not None
    cap = cv2.VideoCapture(str(args.video)) if is_video else open_camera(args)
    if not cap.isOpened():
        print(f"[INSPECT] 입력을 열 수 없습니다: {args.video if is_video else args.camera}", flush=True)
        return
    video_fps = (cap.get(cv2.CAP_PROP_FPS) or 30.0) if is_video else 15.0
    # 첫 추론은 CUDA 초기화로 수 초가 걸려서, 그대로 두면 시작 직후 FRAME_GAP(250ms 초과)으로
    # 판정이 한 번 끊긴다 — 타임스탬프를 재기 전에 미리 한 번 돌려둔다.
    model.predict(np.zeros((args.height, args.width, 3), np.uint8), conf=conf, verbose=False)
    print(f"[INSPECT] 시작 — {service.recipe.recipe_id}, 'q' 종료 / [1/2/3] 레시피 / [n] 새 제품", flush=True)

    writer = None
    fps, previous_key, frame_index = 0.0, None, 0
    started = last_tick = time.monotonic()
    while True:
        ok, frame = cap.read()
        if not ok or (args.max_frames and frame_index >= args.max_frames):
            break
        if args.droidcam_watermark:
            frame = remove_droidcam_watermark(frame)

        timestamp_ms = frame_index / video_fps * 1000.0 if is_video else (time.monotonic() - started) * 1000.0
        result = model.predict(frame, conf=conf, verbose=False)[0]
        detection_frame, info = adapter.convert(result, frame, timestamp_ms)
        snapshot = service.update(detection_frame)

        now = time.monotonic()
        instant = 1.0 / max(now - last_tick, 1e-6)
        last_tick = now
        fps = instant if fps == 0.0 else 0.9 * fps + 0.1 * instant

        key = (snapshot.phase, snapshot.status, snapshot.stable, tuple(i.code + f":H{i.hole_id}" for i in snapshot.candidate.issues))
        if key != previous_key:
            print(f"[{timestamp_ms / 1000:7.2f}s] {snapshot.phase.value:15} | {snapshot.status.value:11} | "
                  f"stable={snapshot.stable!s:5} | {list(key[3])}", flush=True)
            previous_key = key

        annotated = hud.draw(frame, snapshot, detection_frame, info, service.recipe, fps)
        if args.save_video:
            if writer is None:
                args.save_video.parent.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(str(args.save_video), cv2.VideoWriter_fourcc(*"mp4v"), video_fps,
                                         (annotated.shape[1], annotated.shape[0]))
            writer.write(annotated)
        frame_index += 1

        if not args.no_window:
            cv2.imshow("RT-DETR Live Inspection (q: quit)", annotated)
            pressed = cv2.waitKey(1) & 0xFF
            if pressed == ord("q"):
                break
            if pressed in (ord("1"), ord("2"), ord("3")):
                service.reset(recipes[int(chr(pressed))])
                adapter.reset()
                previous_key = None
            elif pressed == ord("n"):
                service.reset()
                adapter.reset()
                previous_key = None

    cap.release()
    if writer is not None:
        writer.release()
        print(f"[INSPECT] 저장: {args.save_video}", flush=True)
    cv2.destroyAllWindows()
    print(f"[INSPECT] 종료 — {frame_index}프레임 처리", flush=True)


if __name__ == "__main__":
    main()
