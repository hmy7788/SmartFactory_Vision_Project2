"""추론 — 사진 한 장을 넣으면 (클래스, 레시피, 확신도, unknown 여부) 를 돌려준다.

softmax 는 언제나 답을 하나 찍는다. 미완성 조립체를 넣어도 model_a/b/c 중 하나가 나온다.
그래서 최고 확률이 unknown_threshold 보다 낮으면 unknown 으로 표시한다 — 룰베이스와 대조할 때
"분류기가 확신 없음" 을 "틀렸다" 와 구분하기 위해서다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .dataset import load_image, load_settings


@dataclass
class ClassifyResult:
    label: str                      # 최고 확률 클래스 (unknown 이어도 채운다)
    recipe_id: str | None           # class_to_recipe 매핑 결과. 매핑에 없으면 None
    confidence: float               # 최고 확률
    unknown: bool                   # confidence < threshold
    probs: dict = field(default_factory=dict)   # 클래스별 확률

    def matches(self, recipe_id: str) -> bool:
        """작업지시 레시피와 같은가. unknown 이면 False — 확신 없는 일치는 일치로 치지 않는다."""
        return (not self.unknown) and self.recipe_id == recipe_id


def decide(probs, classes: list[str], threshold: float, class_to_recipe: dict | None = None) -> ClassifyResult:
    """확률 벡터 → 결과. torch 없이 numpy 로만 (테스트·웹에서 그대로 재사용)."""
    p = np.asarray(probs, dtype=float).reshape(-1)
    if p.shape[0] != len(classes):
        raise ValueError(f"확률 {p.shape[0]}개, 클래스 {len(classes)}개 — 체크포인트와 클래스 순서가 어긋남")
    i = int(p.argmax())
    label = classes[i]
    mapping = class_to_recipe or {}
    return ClassifyResult(label=label, recipe_id=mapping.get(label), confidence=float(p[i]),
                          unknown=bool(p[i] < threshold), probs={c: float(v) for c, v in zip(classes, p)})


class Classifier:
    """체크포인트를 읽어 추론한다. (torch 필요)

        clf = Classifier.load("model/classifier_resnet18.pt")
        r = clf.predict(frame_bgr)
    """

    def __init__(self, model, meta: dict, device: str = "cpu", unknown_threshold: float | None = None):
        from .dataset import build_transforms
        self.model, self.meta, self.device = model, meta, device
        self.classes: list[str] = list(meta["classes"])
        self.class_to_recipe: dict = dict(meta.get("class_to_recipe") or {})
        self.threshold = float(meta.get("unknown_threshold", 0.6) if unknown_threshold is None else unknown_threshold)
        self.tf = build_transforms(int(meta["img_size"]), train=False)

    @classmethod
    def load(cls, path: Path | str, device: str = "cpu", unknown_threshold: float | None = None) -> "Classifier":
        from .model import load_checkpoint
        model, meta = load_checkpoint(path, device)
        return cls(model, meta, device, unknown_threshold)

    def probabilities(self, images) -> np.ndarray:
        """여러 장 → (N, n_classes) 확률."""
        import torch
        batch = torch.stack([self.tf(load_image(x)) for x in images]).to(self.device)
        with torch.no_grad():
            logits = self.model(batch)
            return torch.softmax(logits, dim=1).cpu().numpy()

    def predict(self, image) -> ClassifyResult:
        return decide(self.probabilities([image])[0], self.classes, self.threshold, self.class_to_recipe)

    def predict_batch(self, images) -> list[ClassifyResult]:
        return [decide(p, self.classes, self.threshold, self.class_to_recipe) for p in self.probabilities(images)]


def main(argv=None):
    """python -m src.classification.predict --weights model/classifier_resnet18.pt 사진1 사진2 …"""
    import argparse
    ap = argparse.ArgumentParser(description="완성 조립체 사진 분류")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--weights", default="model/classifier_resnet18.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threshold", type=float, default=None, help="unknown 기준 (기본: 체크포인트 값)")
    a = ap.parse_args(argv)
    clf = Classifier.load(a.weights, a.device, a.threshold)
    for path, r in zip(a.images, clf.predict_batch(a.images)):
        probs = "  ".join(f"{k} {v:.2f}" for k, v in r.probs.items())
        flag = "  (unknown — 확신 부족)" if r.unknown else ""
        print(f"{Path(path).name:28} → {r.label} ({r.recipe_id})  conf {r.confidence:.2f}{flag}   [{probs}]")


if __name__ == "__main__":
    main()
