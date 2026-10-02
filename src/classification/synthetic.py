"""가짜 완성체 사진 — 파이프라인 smoke test 용 (실제 학습엔 쓰지 않는다).

검은 배경 위에 가로 막대 하나와 세로 막대를 그린다. 클래스마다 세로 막대의 자리와 길이가 다르다:
    model_a: 왼쪽 끝에 짧은 것 + 오른쪽에 긴 것      (recipe_1 의 모양)
    model_b: 왼쪽 끝과 가운데에 짧은 것 두 개          (recipe_2)
    model_c: 두 번째 자리에 긴 것 하나                 (recipe_3)
aabb 와 같은 폴더 모양(images/train, images/test)으로 쓴다.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw

SHAPES = {
    "model_a": [(0, "short"), (3, "long")],
    "model_b": [(0, "short"), (2, "short")],
    "model_c": [(1, "long")],
}


def draw_assembly(label: str, size=(320, 180), rng: random.Random | None = None) -> Image.Image:
    rng = rng or random.Random()
    w, h = size
    img = Image.new("RGB", size, (12 + rng.randint(0, 25),) * 3)
    d = ImageDraw.Draw(img)
    bar_w, bar_h = int(w * 0.42), int(h * 0.11)
    x0 = rng.randint(int(w * 0.15), int(w * 0.4)); y0 = rng.randint(int(h * 0.55), int(h * 0.7))
    wood = (205 + rng.randint(-15, 15), 190 + rng.randint(-15, 15), 150)
    d.rectangle([x0, y0, x0 + bar_w, y0 + bar_h], fill=wood)
    pitch = bar_w / 5
    for k in range(5):
        cx = x0 + pitch * (k + 0.5)
        d.ellipse([cx - 4, y0 + bar_h / 2 - 4, cx + 4, y0 + bar_h / 2 + 4], fill=(30, 30, 30))
    for hole, kind in SHAPES[label]:
        cx = x0 + pitch * (hole + 0.5)
        length = int(h * (0.28 if kind == "short" else 0.42))
        d.rectangle([cx - bar_h / 2, y0 - length, cx + bar_h / 2, y0 + bar_h / 2], fill=wood)
        bolt = (240, 200, 40) if kind == "short" else (240, 120, 30)
        d.ellipse([cx - 6, y0 + bar_h / 2 - 6, cx + 6, y0 + bar_h / 2 + 6], fill=bolt)
    if rng.random() < 0.5:
        img = img.rotate(rng.uniform(-180, 180), resample=Image.BILINEAR, fillcolor=(15, 15, 15))
    return img


def make_dataset(root: Path | str, per_class_train: int = 8, per_class_test: int = 3, size=(320, 180), seed: int = 0) -> Path:
    root = Path(root)
    rng = random.Random(seed)
    for split, n in (("train", per_class_train), ("test", per_class_test)):
        d = root / "images" / split; d.mkdir(parents=True, exist_ok=True)
        for label in SHAPES:
            for i in range(n):
                draw_assembly(label, size, rng).save(d / f"{label}_{i + 1:03d}.png")
    return root
