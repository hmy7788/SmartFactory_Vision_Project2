"""완성 조립체 사진 데이터셋 — 폴더를 훑어 (경로, 클래스, split) 목록을 만든다.

읽는 폴더 모양 두 가지:

1) aabb 식 (Roboflow/YOLO 내보내기 그대로). 파일명 앞부분이 클래스다.
       <root>/images/train/model_a_001.png
       <root>/images/test/model_b_005.png
2) 클래스 폴더 식.
       <root>/train/model_a/xxx.png
       <root>/test/model_c/yyy.jpg

두 경우 모두 split 은 train / test 뿐이다 (CLAUDE.md: Val 없이 Train/Test).
클래스 이름은 정렬해서 인덱스를 매긴다 — 체크포인트에 그 순서를 같이 저장하므로
학습 때와 추론 때의 인덱스가 어긋날 일은 없다.

이 모듈은 torch 없이 import 된다. 변환(transform)을 만드는 함수만 안에서 torchvision 을 부른다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "config" / "classification.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}
NAME_RE = re.compile(r"^(?P<cls>[A-Za-z]+_[A-Za-z0-9]+)_\d+$")     # model_a_001 → model_a
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str
    split: str          # "train" | "test"


def load_settings(path: Path | None = None) -> dict:
    """config/classification.json — class_to_recipe · unknown_threshold · arch · img_size."""
    p = Path(path) if path else SETTINGS_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("class_to_recipe", {})
    data.setdefault("unknown_threshold", 0.6)
    data.setdefault("arch", "resnet18")
    data.setdefault("img_size", 448)
    return data


def _class_from_name(path: Path) -> str | None:
    m = NAME_RE.match(path.stem)
    return m.group("cls") if m else None


def scan(root: Path | str, class_prefix: str = "model_") -> list[Sample]:
    """root 아래에서 완성체 사진을 찾는다. 반환은 경로순 정렬 — 재현 가능."""
    root = Path(root)
    out: list[Sample] = []
    seen = set()
    # 1) aabb 식: images/<split>/<class>_NNN.<ext>
    for split in ("train", "test"):
        d = root / "images" / split
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix.lower() not in IMAGE_EXTS:
                    continue
                cls = _class_from_name(p)
                if cls and cls.startswith(class_prefix):
                    out.append(Sample(p, cls, split)); seen.add(p)
    # 2) 클래스 폴더 식: <split>/<class>/*.<ext>
    for split in ("train", "test"):
        d = root / split
        if d.is_dir():
            for cdir in sorted(x for x in d.iterdir() if x.is_dir()):
                for p in sorted(cdir.iterdir()):
                    if p.suffix.lower() in IMAGE_EXTS and p not in seen:
                        out.append(Sample(p, cdir.name, split)); seen.add(p)
    return out


def split(samples: list[Sample], name: str) -> list[Sample]:
    return [s for s in samples if s.split == name]


def class_names(samples: list[Sample]) -> list[str]:
    return sorted({s.label for s in samples})


def summary(samples: list[Sample]) -> str:
    """사람이 읽는 한 줄: train 85 (model_a 17 · model_b 34 · model_c 34) / test 15 (...)"""
    parts = []
    for sp in ("train", "test"):
        c = Counter(s.label for s in samples if s.split == sp)
        inner = " · ".join(f"{k} {v}" for k, v in sorted(c.items()))
        parts.append(f"{sp} {sum(c.values())} ({inner})")
    return " / ".join(parts)


def letterbox(img: Image.Image, size: int, fill=(0, 0, 0)) -> Image.Image:
    """긴 변을 size 로 맞추고 정사각형이 되게 검은색으로 채운다 (16:9 사진 → 위아래 띠).

    비율을 안 바꾸는 이유: 클래스를 가르는 단서가 "막대 길이" 라서, 가로세로를 따로 늘이면
    3구 막대와 2구 막대의 길이 관계가 사진마다 달라진다. 회전 증강을 위해서도 정사각형이 편하다.
    """
    img = img.convert("RGB")
    w, h = img.size
    scale = size / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), fill)
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def load_image(x) -> Image.Image:
    """경로 · PIL 이미지 · OpenCV 프레임(BGR ndarray) → RGB PIL 이미지."""
    if isinstance(x, Image.Image):
        return x.convert("RGB")
    if isinstance(x, (str, Path)):
        with Image.open(x) as im:
            return im.convert("RGB")
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            arr = x
            if arr.ndim == 3 and arr.shape[2] == 3:
                arr = arr[:, :, ::-1]                       # OpenCV 는 BGR
            elif arr.ndim == 3 and arr.shape[2] == 4:
                arr = arr[:, :, [2, 1, 0]]
            return Image.fromarray(np.ascontiguousarray(arr)).convert("RGB")
    except ImportError:
        pass
    raise TypeError(f"이미지로 못 읽는 입력: {type(x)}")


# ── torchvision 변환 (여기서만 torch 를 부른다) ──
def build_transforms(img_size: int, train: bool):
    """학습/평가 변환. 증강은 촬영 조건에서 나온 것만 쓴다.

    - 회전 ±180°: 완성체는 아무 각도로 놓인다 (model_b/c 사진에 실제로 있음, model_a 엔 없음 → 증강으로 채움)
    - 이동 ±8%: 자리가 매번 다르다
    - 밝기·대비·채도 약간: 촬영 세션 두 번의 조명이 다르다 (밝은 회색 배경 / 검은 배경)
    - 좌우 반전 없음: 거울상은 다른 사양이 된다 (H2 에 붙은 3구 ↔ H4 에 붙은 3구)
    - 크기 흔들기(RandomResizedCrop) 없음: 카메라 높이가 고정이라 막대 길이가 그대로 단서다
    """
    from torchvision import transforms as T

    class Letterbox:
        def __init__(self, size): self.size = size
        def __call__(self, img): return letterbox(img, self.size)

    norm = T.Normalize(IMAGENET_MEAN, IMAGENET_STD)
    if not train:
        return T.Compose([Letterbox(img_size), T.ToTensor(), norm])
    return T.Compose([
        Letterbox(img_size),
        T.RandomRotation(180, fill=0),
        T.RandomAffine(degrees=0, translate=(0.08, 0.08), fill=0),
        T.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.02),
        T.ToTensor(),
        norm,
    ])


def make_torch_dataset(samples: list[Sample], classes: list[str], img_size: int, train: bool):
    """torch Dataset — (tensor, label_index)."""
    import torch
    from torch.utils.data import Dataset

    tf = build_transforms(img_size, train)
    index = {c: i for i, c in enumerate(classes)}

    class _DS(Dataset):
        def __len__(self): return len(samples)
        def __getitem__(self, i):
            s = samples[i]
            img = load_image(s.path)
            return tf(img), torch.tensor(index[s.label], dtype=torch.long)

    return _DS()
