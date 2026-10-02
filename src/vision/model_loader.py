"""가중치(.pt) 하나를 받아 알맞은 ultralytics 클래스로 연다 — UI 에 다른 모델을 넣어 돌릴 때 쓰는 한 곳.

    YOLO 계열 (v8 · 11 · 26 …, task obb 또는 detect) → ultralytics.YOLO
    RT-DETR (task detect)                             → ultralytics.RTDETR
        YOLO 로 열어도 열리긴 하지만 후처리가 달라 박스가 틀리게 나온다. 그래서 체크포인트 안의
        모델 클래스 이름(RTDETRDetectionModel)을 보고 자동으로 RTDETR 로 다시 연다.

클래스 이름은 모델마다 다를 수 있다 (볼트_주황 / bolt_2 / orange_bolt …). 코어가 아는 이름은 5개뿐이라
매핑 파일로 맞춘다 — resolve_mapping() 참고. 매핑 값이 null 인 이름은 버린다 (손·조립체 같은 추가 클래스).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.contracts.detections import CLASSES

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAPPING = ROOT / "config/class_mapping.json"
MODEL_TYPES = ("auto", "yolo", "rtdetr")


@dataclass
class ModelInfo:
    path: str
    kind: str                      # "yolo" | "rtdetr"
    task: str | None               # "obb" | "detect" | 그 밖 (segment 등 — 이 시스템엔 못 씀)
    names: dict = field(default_factory=dict)
    size_mb: float = 0.0

    @property
    def label(self) -> str:        # 화면·로그용 한 줄: "yolo26n_obb.pt · yolo · obb"
        return f"{Path(self.path).name} · {self.kind} · {self.task}"


def _is_rtdetr(model) -> bool:
    net = getattr(model, "model", None)
    return "RTDETR" in type(model).__name__ or "RTDETR" in type(net).__name__


def load_model(weights, model_type: str = "auto"):
    """(ultralytics 모델, ModelInfo). model_type: auto(기본) · yolo · rtdetr."""
    if model_type not in MODEL_TYPES:
        raise ValueError(f"model_type 은 {MODEL_TYPES} 중 하나: {model_type}")
    path = Path(weights)
    if not path.exists() and (ROOT / path).exists():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"가중치 파일이 없습니다: {weights}")
    from ultralytics import YOLO
    model = None
    if model_type in ("auto", "yolo"):
        model = YOLO(str(path))
    if model_type == "rtdetr" or (model_type == "auto" and _is_rtdetr(model)):
        if model is None or type(model).__name__ != "RTDETR":
            from ultralytics import RTDETR
            model = RTDETR(str(path))
        kind = "rtdetr"
    else:
        kind = "yolo"
    names = {int(k): str(v) for k, v in dict(getattr(model, "names", {}) or {}).items()}
    info = ModelInfo(str(path), kind, getattr(model, "task", None), names, round(path.stat().st_size / 1e6, 1))
    return model, info


def resolve_mapping(weights=None, class_map=None) -> Path:
    """쓸 매핑 파일: --class-map 로 준 것 > 가중치 옆 '<이름>.classes.json' > config/class_mapping.json."""
    if class_map:
        p = Path(class_map)
        return p if p.is_absolute() or p.exists() else ROOT / p
    if weights:
        side = Path(weights).with_suffix("").as_posix() + ".classes.json"
        for cand in (Path(side), ROOT / side):
            if cand.exists():
                return cand
    return DEFAULT_MAPPING


def load_mapping(path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def check_names(names: dict, mapping: dict) -> tuple[bool, list[str]]:
    """모델 클래스 이름이 코어 5클래스로 이어지는가. (돌릴 수 있는가, 설명 줄들)

    - 매핑에도 없고 5클래스 이름도 아닌 이름이 있으면 못 돌린다 (그 이름이 잡히는 순간 프레임 전체가 보류가 된다).
    - 5클래스 중 모델이 못 내는 것이 있으면 경고만 (그 부품이 들어가는 레시피는 PASS 가 안 나온다).
    """
    lines, mapped = [], {}
    for name in names.values():
        mapped[name] = mapping[name] if name in mapping else name
    unknown = sorted(n for n, v in mapped.items() if v is not None and v not in CLASSES)
    ignored = sorted(n for n, v in mapped.items() if v is None)
    missing = sorted(CLASSES - {v for v in mapped.values() if v})
    pairs = ", ".join(f"{n}→{v}" for n, v in mapped.items() if v and n != v)
    lines.append(f"클래스 {len(names)}개: " + (pairs + " (매핑)" if pairs else "코어 이름 그대로")
                 + (f" · 무시 {ignored}" if ignored else ""))
    if unknown:
        lines.append(f"!! 코어가 모르는 이름: {unknown}")
        lines.append("   → 매핑 파일에 \"모델이름\": \"bolt_1|bolt_2|mother_part|part_2hole|part_3hole\" 로 적거나, "
                     "안 쓰는 클래스면 \"모델이름\": null")
        lines.append("   매핑 파일은 가중치 옆 <가중치이름>.classes.json 을 만들면 그 모델에만 적용됩니다 "
                     "(없으면 config/class_mapping.json).")
    if missing:
        lines.append(f"!  모델이 못 내는 부품: {missing} — 이 부품이 들어가는 레시피는 PASS 가 나오지 않습니다")
    return not unknown, lines
