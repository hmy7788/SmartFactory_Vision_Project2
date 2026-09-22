"""프레임 소스 — 파이프라인에 (DetectionFrame, JPEG|None) 을 공급한다.

    DemoSource    카메라·모델 없이 합성 검출로 시나리오를 돌린다 (UI 개발·발표 리허설용)
    JsonlSource   기록해 둔 DetectionFrame JSONL 을 재생한다 (scripts/replay_detections.py 입력 형식)
    CameraSource  실제 웹캠 + YOLO-OBB. 모델 담당이 채운다 — 어디를 채우면 되는지 아래에 적어 뒀다.

세 소스 모두 같은 인터페이스라 server.py 는 --source 옵션만 다르다.
timestamp 는 단조 증가 ms (time.monotonic 기준). 벽시계를 쓰지 않는다 — 코어의 frame gap 판정이 이 값에 걸려 있다.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from math import pi
from pathlib import Path
from typing import Iterator, Protocol

from src.contracts.detections import DetectionFrame, OBBDetection

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
    → 정정(PASS) → Mother 26° 기울임(HOLD) → 복귀(PASS) → [작업 완료] 를 누를 때까지 PASS 유지
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
            (26 * pi / 180, correct, 1.2),
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


# ── 실제 카메라 (모델 담당이 채운다) ─────────────────────
class CameraSource:
    """웹캠 → YOLO-OBB → DetectionFrame. 아래 뼈대대로 채우면 server.py --source camera 로 바로 붙는다.

        import cv2
        from ultralytics import YOLO
        from src.vision.detection_adapter import from_ultralytics

        cap = cv2.VideoCapture(index); model = YOLO(weights); mapping = json.load(open("config/class_mapping.json"))
        while True:
            ok, img = cap.read()
            ts = now_ms()                                   # 캡처 시각. 추론이 끝난 시각이 아니다
            result = model.predict(img, conf=0.25, verbose=False)[0]     # 후보는 낮게, 판정 임계는 config 가 0.5 로 거른다
            frame = from_ultralytics(result, self.frame_id, ts, mapping)  # xywhr 이 원본 픽셀인지 확인 (resize 했다면 복원)
            jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            yield frame, jpeg

    카메라 오류 시에는 DetectionFrame(frame_id, ts, (), input_valid=False) 를 내보낸다 (docs/state_machine_handoff.md).
    """
    has_video = True

    def __init__(self, index: int = 0, weights: str = "model/yolo_obb_parts.pt", frame_size=(1280, 720)):
        self.index, self.weights, self.frame_size = index, weights, tuple(frame_size)
        self.frame_id = 0

    def reset(self, recipe) -> None:
        pass

    def frames(self) -> Iterator[Frame]:
        raise NotImplementedError("CameraSource: 모델 담당이 web/source.py 의 docstring 대로 채운다")
