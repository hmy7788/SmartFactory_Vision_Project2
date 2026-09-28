"""프레임 소스 — 파이프라인에 (DetectionFrame, JPEG|None) 을 공급한다.

    DemoSource    카메라·모델 없이 합성 검출로 시나리오를 돌린다 (UI 개발·발표 리허설용)
    JsonlSource   기록해 둔 DetectionFrame JSONL 을 재생한다 (scripts/replay_detections.py 입력 형식)
    CameraSource  실제 웹캠 + 검출 모델(RT-DETR/YOLO/YOLO-OBB/rule_based, --model-type).
                  scripts/live_inspection.py와 같은 어댑터(src/vision/rtdetr_adapter.py,
                  src/vision/rule_based_adapter.py)를 그대로 쓴다.

세 소스 모두 같은 인터페이스라 server.py 는 --source 옵션만 다르다.
timestamp 는 단조 증가 ms (time.monotonic 기준). 벽시계를 쓰지 않는다 — 코어의 frame gap 판정이 이 값에 걸려 있다.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from math import pi
from pathlib import Path
from typing import Iterator, Protocol

from src.contracts.detections import DetectionFrame, OBBDetection
from src.vision.detection_adapter import from_ultralytics
from src.vision.rtdetr_adapter import RTDETRAdapter
from src.vision.rule_based_adapter import RuleBasedAdapter

# --weights 생략 시 --model-type별 기본 경로 (scripts/live_inspection.py와 동일한 규칙).
DEFAULT_WEIGHTS = {
    "rtdetr": "runs/rtdetr/full_run/weights/best.pt",
    "yolo": None,
    "yolo-obb": "model/yolo_obb_parts.pt",
    "rule_based": None,
}

Frame = tuple[DetectionFrame, bytes | None]


def now_ms() -> int:
    return int(time.monotonic() * 1000)


class Source(Protocol):
    frame_size: tuple[int, int]         # (width, height) — 오버레이 좌표계
    has_video: bool                     # JPEG 를 주는가

    def frames(self) -> Iterator[Frame]: ...
    def reset(self, recipe) -> None: ...        # 새 제품 시작 (데모는 시나리오를 처음부터)


# ── 합성 데모 ─────────────────────────────────────────────
def demo_config(config: dict, speed: float) -> dict:
    """데모 배속용 config. 시나리오 단계만 짧아지면 코어의 안정화 창(1000ms/400ms)이 끝나기 전에
    다음 단계로 넘어가 NG·PASS 가 확정되지 않는다. 그래서 두 창도 같은 배율로 줄인다.
    frame gap 은 건드리지 않는다 (프레임 간격은 배속과 무관). 실제 소스에는 쓰지 않는다."""
    if speed == 1.0:
        return config
    return dict(config,
                stable_duration_ms=max(1, int(config["stable_duration_ms"] / speed)),
                material_stable_duration_ms=max(1, int(config["material_stable_duration_ms"] / speed)))


class DemoSource:
    """레시피에 맞춘 시나리오를 실시간 속도로 재생한다.

    재료 부족 → 재료 초과(NG) → 정확(READY→조립) → 빈 Mother → 첫 자리 조립 → 두 번째 자리 볼트 오조립(NG)
    → 정정(PASS) → Mother 26° 기울임 3.6초(코어는 HOLD. 작업 화면은 PASS 유지 + [작업 완료] 잠금, 3초 뒤 'Mother 를 똑바로' 한 줄) → 복귀(PASS) → [작업 완료] 를 누를 때까지 PASS 유지
    """
    frame_size = (1200, 900)
    has_video = False

    def __init__(self, recipe, config, fps: float = 10.0, speed: float = 1.0):
        """speed: 시나리오 단계 길이를 나누는 배율. 테스트에서 8~10 으로 올려 빨리 돌린다."""
        self.config, self.fps, self.speed = config, fps, speed
        self.frame_id = 0
        self.reset(recipe)

    # 검출 만들기 (scripts/demo_data.py 와 같은 기하 — Mother W=1000, 중심 (600,700))
    def _mother(self, angle=0.0):
        return OBBDetection("m", "mother_part", 0.97, (600, 700), 1000, 160, angle)

    PART_LEN = {"part_2hole": 320, "part_3hole": 500}     # 실물 비율에 가깝게. ROI(미보정 기본값)보다 작아도 안에 들어가면 연결된다

    def _placed(self, placement, bolt=None, part=None):
        x = 600 + self.config["hole_alphas"][placement.mother_hole - 1] * 1000
        cls = part or placement.part
        length = self.PART_LEN[cls]
        # 아래 끝이 Hole 에 걸치도록 위로 세운다 (-v = 화면 위). anchor 추정이 Hole 근처(±0.1W)에 떨어진다.
        return [OBBDetection(f"b{placement.mother_hole}", bolt or placement.bolt, 0.9, (x, 700), 80, 80, 0),
                OBBDetection(f"p{placement.mother_hole}", cls, 0.88, (x, 700 - length / 2 + 40), length, 90, pi / 2)]

    def _scattered(self, extra=None):
        """재료 확인용 — Mother 에서 떨어진 자리에 흩어 놓는다."""
        items = []
        for k, p in enumerate(self.recipe.placements):
            items.append(OBBDetection(f"sb{k}", p.bolt, 0.9, (120 + k * 400, 120), 80, 80, 0))
            items.append(OBBDetection(f"sp{k}", p.part, 0.86, (330 + k * 400, 120), self.PART_LEN[p.part], 90, 0))
        if extra:
            items.append(OBBDetection("extra", extra, 0.83, (980, 320), self.PART_LEN[extra], 90, 0.3))
        return items

    def _build_stages(self):
        pl = self.recipe.placements
        wrong_bolt = "bolt_1" if pl[-1].bolt == "bolt_2" else "bolt_2"
        correct = [d for p in pl for d in self._placed(p)]
        first = self._placed(pl[0])
        second_wrong = first + (self._placed(pl[1], bolt=wrong_bolt) if len(pl) > 1
                                else [OBBDetection("x5", "bolt_1", 0.85, (600 + 0.4 * 1000, 700), 80, 80, 0)])
        return [  # (Mother 각도, 나머지 검출, 지속 초)
            (0.0, [], 1.0),
            (0.0, self._scattered(extra=pl[-1].part), 1.6),
            (0.0, self._scattered(), 1.6),
            (0.0, [], 1.0),
            (0.0, first, 1.4),
            (0.0, second_wrong, 2.0),
            (0.0, correct, 1.6),
            (26 * pi / 180, correct, 3.6),
            (0.0, correct, None),          # None = 다음 reset 까지 유지
        ]

    def reset(self, recipe) -> None:
        self.recipe = recipe
        self.stages = self._build_stages()
        self.stage_i, self.stage_started = 0, time.monotonic()

    def frames(self) -> Iterator[Frame]:
        period = 1.0 / self.fps
        while True:
            angle, dets, hold = self.stages[self.stage_i]
            if hold is not None and time.monotonic() - self.stage_started > hold / self.speed:
                self.stage_i = min(self.stage_i + 1, len(self.stages) - 1)
                self.stage_started = time.monotonic()
                continue
            self.frame_id += 1
            yield DetectionFrame(self.frame_id, now_ms(), tuple([self._mother(angle)] + dets)), None
            time.sleep(period)


# ── JSONL 재생 ────────────────────────────────────────────
class JsonlSource:
    """DetectionFrame JSONL (한 줄에 한 프레임) 을 원래 간격대로 재생한다. 끝나면 처음부터."""
    has_video = False

    def __init__(self, path: str | Path, frame_size=(1280, 720), loop: bool = True):
        self.path, self.frame_size, self.loop = Path(path), tuple(frame_size), loop
        self.frame_id = 0

    def reset(self, recipe) -> None:      # 기록 재생은 레시피와 무관
        pass

    def frames(self) -> Iterator[Frame]:
        while True:
            prev_ts = None
            with self.path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    if prev_ts is not None:
                        time.sleep(max(0.0, (raw["timestamp_ms"] - prev_ts) / 1000.0))
                    prev_ts = raw["timestamp_ms"]
                    frame = DetectionFrame.from_dict(raw)
                    self.frame_id += 1
                    # 기록의 timestamp 대신 단조 증가 시각을 붙인다 — 반복 재생 시 역행 방지
                    yield replace(frame, frame_id=self.frame_id, timestamp_ms=now_ms()), None
            if not self.loop:
                return


# ── 실제 카메라 ────────────────────────────────────────
class CameraSource:
    """웹캠(또는 영상) → 검출 모델 → DetectionFrame + JPEG. --model-type으로 rtdetr(기본)·yolo·
    yolo-obb·rule_based 중 고른다 (scripts/live_inspection.py와 같은 선택지/기본 가중치).

    지키는 것:
      1. timestamp 는 캡처 직후 now_ms(). 추론이 끝난 시각이 아니다 — 코어의 frame gap 판정 기준이라서.
      2. ultralytics Results 의 xywhr/xywh 은 원본 픽셀로 돌아온다 (imgsz 로 줄여 추론해도). 그대로 어댑터에 넘긴다.
         rtdetr/yolo(AABB)는 rtdetr_adapter.py가 mother 각도를 영상에서 복원, yolo-obb는 결과에 각도가
         이미 있어 detection_adapter.from_ultralytics로 바로 변환, rule_based는 모델 없이 영상만으로 검출.
      3. 후보 conf 는 낮게(0.25). 판정 임계 0.5 는 config 가 거른다 — 진단 탭의 confidence 분포가 임계 근처를 보여 줘야 임계를 고를 수 있다.
      4. 한글 클래스명 → 영문 5클래스는 config/class_mapping.json 으로(yolo-obb 경로만 사용). 매핑에 없는
         이름이 나오면 어댑터가 ValueError → 이 소스가 잡아서 input_valid=False 로 낸다 (코어는 HOLD).
      5. 카메라 read 실패 → input_valid=False 프레임을 내고 카메라를 다시 연다. 서버는 죽지 않는다.
      6. weights=None 이고 rule_based 도 아니면 모델 없이 영상만 낸다 (검출 0개). 가중치를 받기 전에
         카메라·구도·해상도를 확인하는 용도. 코어는 Mother 가 없으니 HOLD(보류)를 내고, 화면에는 실제 영상이 뜬다.

    capture / model 은 테스트에서 가짜를 꽂을 수 있게 주입 가능. 실제 실행에서는 None 으로 두면 cv2·ultralytics 를 연다.
    """
    has_video = True

    def __init__(self, index: int = 0, weights: str | None = None, frame_size=(1280, 720),
                 conf: float = 0.25, imgsz: int = 640, mapping_path: str | Path = "config/class_mapping.json",
                 capture=None, model=None, jpeg_quality: int = 80,
                 threaded: bool | None = None, max_fps: float = 20.0, video: str | None = None, loop: bool = True,
                 video_end: str | None = None, model_type: str = "rtdetr", flip_horizontal: bool = False):
        self.index, self.frame_size = index, tuple(frame_size)
        self.model_type = model_type                    # rtdetr(기본) · yolo · yolo-obb · rule_based
        self.flip_horizontal = flip_horizontal          # 카메라가 좌우반전(미러) 영상을 주면 True
        self.weights = weights                          # None = 모델 없이 영상만(--no-model). 기본 경로 결정은 web/server.py 몫
        # 8. 영상 파일 모드: 웹캠 대신 녹화한 조립 영상을 원래 속도로 재생하며 같은 판정을 돌린다.
        #    끝나면 video_end 대로: "hold" 마지막 장면을 계속 보여 준다 (카메라가 완성품을 계속 보는 것과 같다 —
        #    PASS 와 [작업 완료] 버튼이 남는다) · "loop" 처음부터 · "stop" 끝. 새 작업·작업 완료(reset) 는 처음으로 되감는다.
        self.video, self.loop = (str(video) if video else None), loop
        self.video_end = video_end or ("loop" if loop else "stop")
        self.at_end = False                             # 영상 끝에서 마지막 장면을 유지 중인가 (화면 표시용)
        self._rewind = False
        self._last_img = None
        self._video_fps: float | None = None
        self._next_frame_at = 0.0
        self.conf, self.imgsz, self.jpeg_quality = conf, imgsz, jpeg_quality
        # 7. 영상과 추론을 분리한다. 영상은 카메라 속도로 계속 내보내고, 추론은 뒤 스레드에서 되는 만큼만 돌려
        #    가장 최근 결과를 매 프레임에 붙인다. 무거운 모델(RT-DETR, CPU 1~2초)이어도 화면은 끊기지 않고 판정만 늦게 갱신된다.
        #    주입한 가짜 캡처(테스트)는 기본이 동기 — 프레임마다 추론 결과가 결정적으로 붙어야 하니까.
        self.threaded = (capture is None) if threaded is None else threaded
        self.max_fps = max_fps
        self.infer_ms: float | None = None              # 마지막 추론에 걸린 시간 (진단)
        self.result_age_ms: int | None = None           # 화면에 붙은 판정이 몇 ms 전 프레임 것인지 (진단)
        self._latest = None                             # 추론 스레드가 마지막으로 본 (img, ts)
        self._latest_lock = threading.Lock()
        self._result = None                             # (detections, ts, input_valid)
        self._infer_thread = None
        self._infer_stop = threading.Event()
        self.mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8")) if Path(mapping_path).exists() else {}
        self._rtdetr_adapter = RTDETRAdapter(class_mapping=self.mapping)   # rtdetr/yolo(AABB) 전용, 프레임 간 각도 평활화 상태를 들고 있음
        self._rule_adapter = RuleBasedAdapter()                            # rule_based 전용
        self._capture, self._model = capture, model
        self._injected = capture is not None        # 테스트용 가짜 캡처는 다시 열지 않는다
        self.frame_id = 0
        self.last_error: str | None = None          # 진단용 — 마지막으로 프레임을 못 만든 이유

    def reset(self, recipe) -> None:                 # 카메라는 레시피와 무관. 영상 파일이면 처음부터 다시 (다음 제품)
        if self.video:
            self._rewind = True

    # ── 장치·모델 열기 (지연 로딩: import 비용을 서버 시작이 아니라 첫 프레임에) ──
    def _open_capture(self):
        if self._capture is None:
            import cv2, sys
            if self.video:                           # 8. 영상 파일 — 해상도는 파일 그대로, 재생 속도는 파일 fps
                cap = cv2.VideoCapture(self.video)
                fps = cap.get(cv2.CAP_PROP_FPS) or 0
                self._video_fps = fps if 1 <= fps <= 120 else 30.0
                self._next_frame_at = time.perf_counter()
            else:
                backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY   # 윈도우: DSHOW 가 빨리·안정적으로 열린다
                cap = cv2.VideoCapture(self.index, backend)
                # MJPG 를 먼저 요청해야 한다: 윈도우 DSHOW 는 기본이 무압축(YUY2) 이라 C270 1280x720 이 7~15fps 로 떨어지는 일이 흔하다.
                # 순서도 중요 — 코덱 → 해상도 → fps. 카메라가 MJPG 를 모르면 그냥 무시되고 예전처럼 열린다.
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_size[1])
                cap.set(cv2.CAP_PROP_FPS, 30)
                code = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
                fourcc = "".join(chr((code >> 8 * k) & 0xFF) for k in range(4)) if code else "?"
                print(f"[camera {self.index}] {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
                      f"{cap.get(cv2.CAP_PROP_FPS):.0f}fps codec={fourcc}   (실제 처리 fps 는 진단 탭 'core+store 처리 / fps')", flush=True)
            self._capture = cap
        return self._capture

    def _open_model(self):
        if self._model is None and self.model_type != "rule_based":   # 서버는 보통 미리 연 모델을 넘긴다 (web.server.build)
            from ultralytics import RTDETR, YOLO
            self._model = RTDETR(self.weights) if self.model_type == "rtdetr" else YOLO(self.weights)
        return self._model

    def _predict(self, img):
        model = self._open_model()
        # ultralytics: model.predict(...) → list[Results]. 주입한 가짜 모델은 그냥 callable 로 취급.
        if hasattr(model, "predict"):
            return model.predict(img, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        return model(img)

    def _encode(self, img) -> bytes | None:
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
            return buf.tobytes() if ok else None
        except Exception:                            # cv2 없이 가짜 캡처로 돌릴 때
            return None

    def _infer_once(self, img, ts):
        """한 장 추론 → (detections, ts, input_valid). 오류는 last_error 에 남기고 보류 프레임으로."""
        t0 = time.perf_counter()
        try:
            if self.model_type == "rule_based":
                frame, _info = self._rule_adapter.convert(img, ts)
            elif self.model_type == "yolo-obb":
                result = self._predict(img)
                frame = from_ultralytics(result, 0, ts, self.mapping)              # 2, 4
            else:                                     # rtdetr · yolo(detect, AABB)
                result = self._predict(img)
                frame, _info = self._rtdetr_adapter.convert(result, img, ts)
            self.last_error = None
            out = (frame.detections, ts, True)
        except Exception as error:                   # 매핑에 없는 클래스, 모델 오류 등 → 보류 프레임, 서버는 계속
            self.last_error = f"{type(error).__name__}: {error}"
            out = ((), ts, False)
        self.infer_ms = round((time.perf_counter() - t0) * 1000, 1)
        return out

    def _infer_loop(self) -> None:
        """추론 스레드: 가장 최근 프레임만 본다 (밀린 프레임은 버린다)."""
        seen_ts = None
        while not self._infer_stop.is_set():
            with self._latest_lock:
                latest = self._latest
            if latest is None or latest[1] == seen_ts:
                time.sleep(0.005); continue
            img, ts = latest
            seen_ts = ts
            self._result = self._infer_once(img, ts)

    def _start_infer_thread(self) -> None:
        if self._infer_thread is None or not self._infer_thread.is_alive():
            self._infer_stop.clear()
            self._infer_thread = threading.Thread(target=self._infer_loop, name="infer", daemon=True)
            self._infer_thread.start()

    def close(self) -> None:
        self._infer_stop.set()

    def frames(self) -> Iterator[Frame]:
        has_model = self.model_type == "rule_based" or not (self.weights is None and self._model is None)
        if has_model and self.threaded:
            self._open_model()                       # 첫 프레임 전에 가중치를 읽어 둔다 (스레드 안에서 실패하면 보기 어렵다)
            self._start_infer_thread()
        min_interval = 1.0 / self.max_fps if self.max_fps else 0.0
        last_yield = 0.0
        try:
            while True:
                cap = self._open_capture()
                if self._video_fps:                      # 8. 영상 파일: 원래 속도로 (파일은 카메라와 달리 기다려 주지 않는다)
                    wait = self._next_frame_at - time.perf_counter()
                    if wait > 0:
                        time.sleep(wait)
                    self._next_frame_at = max(self._next_frame_at, time.perf_counter() - 1.0) + 1.0 / self._video_fps
                if self._rewind and self._video_fps and not self._injected:
                    import cv2
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # 새 작업·작업 완료 → 영상을 처음부터
                    self._rewind, self.at_end = False, False
                ok, img = cap.read()
                if (not ok or img is None) and self._video_fps and not self._injected:
                    if self.video_end == "stop":
                        return
                    if self.video_end == "hold" and self._last_img is not None:
                        ok, img, self.at_end = True, self._last_img, True     # 영상 끝 → 마지막 장면 유지
                    else:
                        import cv2
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # 영상 끝 → 처음부터
                        ok, img = cap.read()
                if ok and img is not None and self._video_fps:
                    self._last_img = img
                ts = now_ms()                            # 1. 캡처 시각
                self.frame_id += 1
                if not ok or img is None:
                    self.last_error = "camera read failed"
                    yield DetectionFrame(self.frame_id, ts, (), input_valid=False), None
                    self._reopen(); continue
                if self.flip_horizontal:                 # 카메라/드라이버가 좌우반전(미러)해서 주는 경우 되돌림
                    import cv2
                    img = cv2.flip(img, 1)
                h, w = img.shape[:2]
                if (w, h) != self.frame_size:            # 카메라가 요청한 해상도를 안 줄 수 있다 → 실제 크기로 (오버레이 좌표계)
                    self.frame_size = (w, h)
                if not has_model:                        # 6. 모델 없음 — 영상만
                    self.last_error = None
                    yield DetectionFrame(self.frame_id, ts, ()), self._encode(img)
                    continue
                if self.threaded:                        # 7. 영상은 계속, 판정은 최신 추론 결과를 붙인다
                    with self._latest_lock:
                        self._latest = (img, ts)
                    res = self._result
                    if res is None:                      # 첫 추론 전 — 검출 없음(코어는 Mother 없음 → 보류)
                        frame = DetectionFrame(self.frame_id, ts, ())
                        self.result_age_ms = None
                    else:
                        dets, rts, valid = res
                        frame = DetectionFrame(self.frame_id, ts, dets, input_valid=valid)
                        self.result_age_ms = int(ts - rts)
                    if min_interval:                     # 웹소켓·JPEG 부하를 제한 (카메라 30fps → 최대 max_fps)
                        wait = min_interval - (time.perf_counter() - last_yield)
                        if wait > 0:
                            time.sleep(wait)
                        last_yield = time.perf_counter()
                    yield frame, self._encode(img)
                    continue
                dets, _, valid = self._infer_once(img, ts)
                self.result_age_ms = 0
                yield DetectionFrame(self.frame_id, ts, dets, input_valid=valid), self._encode(img)
        finally:
            self._infer_stop.set()

    def _reopen(self) -> None:
        if self._injected:
            return
        try:
            if self._capture is not None and hasattr(self._capture, "release"):
                self._capture.release()
        finally:
            self._capture = None
            time.sleep(0.5)
