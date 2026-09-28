"""
카메라(또는 영상 파일) -> 검출 모델(RT-DETR/YOLO/YOLO-OBB) -> 어댑터 -> InspectionService
-> 한글 HUD 라이브 검사.

재료 확인(필요/현재 개수) -> 조립 검사(H1~H5 구멍별 볼트/부품 배치, 오류 원인 안내) 흐름을
검출 결과로 돌린다. --model-type으로 검출 모델 종류를 고른다:
  - rtdetr(기본): ultralytics RTDETR, 회전 없는 박스만 나오므로 rtdetr_adapter.py가
    mother 각도를 영상에서 복원해서 엔진에 넘긴다.
  - yolo: ultralytics YOLO(detect task), rtdetr와 같은 AABB 출력이라 같은 어댑터를 쓴다.
  - yolo-obb: ultralytics YOLO(obb task, CLAUDE.md 확정 메인 파이프라인). 결과에 각도가
    이미 있어서 영상에서 각도를 복원할 필요가 없다 (detection_adapter.from_ultralytics).
  - rule_based: 학습된 모델이 아예 없음. src/vision/rule_based_adapter.py가 classical
    CV(색상+구멍 개수)만으로 개별 부품을 찾는다. --weights 불필요. 부품이 서로 떨어진
    재료 섹션(오피킹 검출)에서 잘 맞고, 조립 섹션에서 볼트가 이미 꽂힌 부품은 정확도가
    떨어질 수 있다(모듈 docstring의 "한계" 참고).
--weights를 생략하면 --model-type별 기본 경로를 쓴다 (아래 DEFAULT_WEIGHTS, rule_based는 불필요).

⚠️ 원래 엔진(config/mvp.json)은 (1) mother가 ±15° 넘게 기울면 거부하고 (2) H1을 화면 왼쪽으로
   고정해서, 조립체를 다른 방향으로 놓으면 정상 조립도 실패한다. 기본 설정인
   config/rtdetr_live.json은 각도(89.9°)와 좌우 뒤집힘(allow_mirrored_holes)은 풀되, 부품은
   반드시 Mother "위쪽"에만 달려야 한다 — 아래쪽에 달린 부품은 NG(PART_WRONG_SIDE)로 판정한다.
   단, 조립체 전체가 진짜 180도 회전한 경우(구멍 번호와 위/아래가 동시에 뒤집힌 경우)는
   evaluate_symmetric이 예외로 인정해 PASS시킨다 — 한 부품만 반대쪽에 붙은 경우와는 구별된다
   (tests/test_relaxed_orientation.py 참고). 부품이 항상 위/아래 어느 쪽이든 허용되면 되는
   경우 --config에 allow_parts_below:true를 켠 설정을 쓰면 된다. 팀원 원래 동작이 필요하면
   --config config/mvp.json.

사용법 (저장소 루트에서):
    python -m scripts.live_inspection --camera 3 --recipe 3
    python -m scripts.live_inspection --camera 1 --backend msmf --droidcam-watermark
    python -m scripts.live_inspection --video 1.mp4 --recipe 3 --save-video runs/inspection_demo.mp4 --no-window
    python -m scripts.live_inspection --model-type yolo-obb --camera 1 --recipe 3
    python -m scripts.live_inspection --model-type yolo --weights runs/yolo/best.pt --camera 1
    python -m scripts.live_inspection --model-type rule_based --camera 1 --recipe 3

키: [1/2/3] 레시피 선택(초기화)  [n] 새 제품(초기화)  [q] 종료
"""

import argparse
import math
import sys
import time
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from ultralytics import RTDETR, YOLO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "detection"))

from camera_utils import remove_droidcam_watermark  # noqa: E402
from src.app.config import load_config  # noqa: E402
from src.app.hud import Hud  # noqa: E402
from src.app.inspection_service import InspectionService  # noqa: E402
from src.contracts.inspection import Status  # noqa: E402
from src.process.recipe import load_recipe  # noqa: E402
from src.rule_based.hole_count_check import RECIPE_TO_MODEL, classify_model  # noqa: E402
from src.vision.detection_adapter import from_ultralytics  # noqa: E402
from src.vision.rtdetr_adapter import RTDETRAdapter  # noqa: E402
from src.vision.rule_based_adapter import RuleBasedAdapter  # noqa: E402

# --weights를 생략했을 때 --model-type별 기본 가중치. yolo는 저장소에 학습된 기본값이 없어
# None -> 필수 인자로 취급한다. rule_based는 모델이 아예 없어 이 표에 없음(무조건 불필요).
DEFAULT_WEIGHTS = {
    "rtdetr": ROOT / "runs/rtdetr/full_run/weights/best.pt",
    "yolo": None,
    "yolo-obb": ROOT / "model/yolo_obb_parts.pt",
}


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
    parser.add_argument("--model-type", choices=["rtdetr", "yolo", "yolo-obb", "rule_based"], default="rtdetr",
                        help="검출 모델 종류 (기본 rtdetr). yolo-obb는 각도가 결과에 이미 있어 "
                             "영상에서 mother 각도를 복원하지 않는다. rule_based는 학습된 모델 "
                             "없이 classical CV로 검출한다(--weights 불필요)")
    parser.add_argument("--weights", default=None, help="생략하면 --model-type 기본 경로 사용")
    parser.add_argument("--conf", type=float, default=None, help="생략하면 config의 confidence_threshold")
    parser.add_argument("--config", type=Path, default=ROOT / "config/rtdetr_live.json",
                        help="기본은 각도 제한을 풀고 좌우 뒤집힌 번호를 허용하되, 부품은 mother "
                             "위쪽에만 달려야 하는 라이브용 설정(180도 전체 회전은 예외로 인정) "
                             "(팀원 원본은 config/mvp.json)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=["dshow", "msmf"], default="dshow",
                        help="DroidCam 가상 웹캠은 msmf로만 잡히는 경우가 있음")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--exposure", default=None, help="셔터 속도 수동 고정(예: '1/20')")
    parser.add_argument("--droidcam-watermark", action="store_true",
                        help="DroidCam 무료 버전 워터마크 영역을 지우고 추론 (640x480 기준)")
    parser.add_argument("--flip-horizontal", action="store_true",
                        help="카메라 영상이 좌우반전(미러)돼서 나올 때 되돌린다. 코드가 뒤집는 게 아니라 "
                             "카메라/드라이버가 원래 뒤집어서 주는 경우용 (워터마크 제거 뒤에 적용됨)")
    parser.add_argument("--flip-vertical", action="store_true",
                        help="카메라가 상하 거꾸로(180도 돌려 설치 등) 영상을 줄 때 되돌린다. "
                             "--flip-horizontal과 같이 켜면 상하좌우 모두 뒤집힘(워터마크 제거 뒤에 적용됨)")
    parser.add_argument("--video", type=Path, default=None, help="카메라 대신 영상 파일로 실행")
    parser.add_argument("--save-video", type=Path, default=None, help="HUD가 그려진 결과를 mp4로 저장")
    parser.add_argument("--no-window", action="store_true", help="창 없이 실행 (저장/콘솔 로그만)")
    parser.add_argument("--max-frames", type=int, default=0, help="0이면 끝까지")
    args = parser.parse_args()

    is_rule_based = args.model_type == "rule_based"
    model, weights = None, None
    if not is_rule_based:
        weights = Path(args.weights) if args.weights else DEFAULT_WEIGHTS[args.model_type]
        if weights is None:
            parser.error(f"--model-type {args.model_type}는 저장소에 기본 가중치가 없습니다. --weights로 지정하세요.")

    config = load_config(args.config)
    recipes = {n: load_recipe(ROOT / f"config/recipes/recipe_{n}.json") for n in (1, 2, 3)}
    service = InspectionService(config, recipes[args.recipe])
    # yolo-obb는 결과에 각도가 이미 있어 rtdetr_adapter(영상에서 각도 복원)가 필요 없고,
    # rule_based는 아예 자체 어댑터(모델 result 없이 frame만 받음)를 쓴다.
    adapter = RuleBasedAdapter() if is_rule_based else (None if args.model_type == "yolo-obb" else RTDETRAdapter())
    hud = Hud(config)
    conf = args.conf if args.conf is not None else config["confidence_threshold"]

    if is_rule_based:
        print("[INSPECT] 모델 없음 (rule_based: classical CV로 검출)", flush=True)
    else:
        print(f"[INSPECT] 모델 로드 ({args.model_type}): {weights}", flush=True)
        model = RTDETR(str(weights)) if args.model_type == "rtdetr" else YOLO(str(weights))

    is_video = args.video is not None
    cap = cv2.VideoCapture(str(args.video)) if is_video else open_camera(args)
    if not cap.isOpened():
        print(f"[INSPECT] 입력을 열 수 없습니다: {args.video if is_video else args.camera}", flush=True)
        return
    video_fps = (cap.get(cv2.CAP_PROP_FPS) or 30.0) if is_video else 15.0
    if model is not None:
        # 첫 추론은 CUDA 초기화로 수 초가 걸려서, 그대로 두면 시작 직후 FRAME_GAP(250ms 초과)으로
        # 판정이 한 번 끊긴다 — 타임스탬프를 재기 전에 미리 한 번 돌려둔다.
        model.predict(np.zeros((args.height, args.width, 3), np.uint8), conf=conf, verbose=False)
    print(f"[INSPECT] 시작 — {service.recipe.recipe_id}, 'q' 종료 / [1/2/3] 레시피 / [n] 새 제품", flush=True)

    writer = None
    final_check = None
    fps, previous_key, frame_index = 0.0, None, 0
    started = last_tick = time.monotonic()
    while True:
        ok, frame = cap.read()
        if not ok or (args.max_frames and frame_index >= args.max_frames):
            break
        if args.droidcam_watermark:
            frame = remove_droidcam_watermark(frame)
        if args.flip_horizontal and args.flip_vertical:
            frame = cv2.flip(frame, -1)
        elif args.flip_horizontal:
            frame = cv2.flip(frame, 1)
        elif args.flip_vertical:
            frame = cv2.flip(frame, 0)

        timestamp_ms = frame_index / video_fps * 1000.0 if is_video else (time.monotonic() - started) * 1000.0
        if is_rule_based:
            detection_frame, info = adapter.convert(frame, timestamp_ms)
        else:
            result = model.predict(frame, conf=conf, verbose=False)[0]
            if adapter is not None:
                detection_frame, info = adapter.convert(result, frame, timestamp_ms)
            else:
                detection_frame = from_ultralytics(result, frame_index, timestamp_ms)
                mother = next((d for d in detection_frame.detections if d.class_name == "mother_part"), None)
                info = {"angle_source": "obb", "raw_boxes": len(detection_frame.detections),
                        "after_dedup": len(detection_frame.detections),
                        "mother_angle_deg": math.degrees(mother.angle_rad) if mother else None}
        snapshot = service.update(detection_frame)

        if final_check is None and snapshot.status == Status.PASS and snapshot.stable:
            expected = RECIPE_TO_MODEL.get(service.recipe.recipe_id)
            try:
                model_name, message, _ = classify_model(frame)
            except Exception as error:  # noqa: BLE001 - 검증 실패도 화면에 보여줘야 함
                model_name, message = None, f"룰베이스 검증 오류: {error}"
            final_check = {"expected": expected, "model": model_name, "message": message}

        now = time.monotonic()
        instant = 1.0 / max(now - last_tick, 1e-6)
        last_tick = now
        fps = instant if fps == 0.0 else 0.9 * fps + 0.1 * instant

        key = (snapshot.phase, snapshot.status, snapshot.stable, tuple(i.code + f":H{i.hole_id}" for i in snapshot.candidate.issues))
        if key != previous_key:
            print(f"[{timestamp_ms / 1000:7.2f}s] {snapshot.phase.value:15} | {snapshot.status.value:11} | "
                  f"stable={snapshot.stable!s:5} | {list(key[3])}", flush=True)
            previous_key = key

        annotated = hud.draw(frame, snapshot, detection_frame, info, service.recipe, fps, final_check)
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
                if adapter is not None:
                    adapter.reset()
                previous_key = None
                final_check = None
            elif pressed == ord("n"):
                service.reset()
                if adapter is not None:
                    adapter.reset()
                previous_key = None
                final_check = None

    cap.release()
    if writer is not None:
        writer.release()
        print(f"[INSPECT] 저장: {args.save_video}", flush=True)
    cv2.destroyAllWindows()
    print(f"[INSPECT] 종료 — {frame_index}프레임 처리", flush=True)


if __name__ == "__main__":
    main()
