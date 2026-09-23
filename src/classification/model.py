"""모델 만들기 · 체크포인트 저장/읽기. (torch 필요)

체크포인트 하나에 가중치 + 클래스 순서 + 입력 크기 + 정규화 + 레시피 매핑을 전부 넣는다.
추론 쪽이 학습 때 설정을 따로 알 필요가 없게 하기 위해서다.
"""
from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

ARCHS = ("resnet18", "resnet34", "efficientnet_b0", "mobilenet_v3_small", "convnext_tiny")
CHECKPOINT_FORMAT = 1


def build_model(arch: str, n_classes: int, pretrained: bool = True) -> nn.Module:
    """torchvision 모델의 마지막 분류 층만 n_classes 로 바꾼다."""
    from torchvision import models

    if arch not in ARCHS:
        raise ValueError(f"지원하지 않는 arch: {arch} (가능: {', '.join(ARCHS)})")
    weights = "DEFAULT" if pretrained else None
    if arch == "resnet18":
        m = models.resnet18(weights=weights); m.fc = nn.Linear(m.fc.in_features, n_classes)
    elif arch == "resnet34":
        m = models.resnet34(weights=weights); m.fc = nn.Linear(m.fc.in_features, n_classes)
    elif arch == "efficientnet_b0":
        m = models.efficientnet_b0(weights=weights); m.classifier[1] = nn.Linear(m.classifier[1].in_features, n_classes)
    elif arch == "mobilenet_v3_small":
        m = models.mobilenet_v3_small(weights=weights); m.classifier[3] = nn.Linear(m.classifier[3].in_features, n_classes)
    else:  # convnext_tiny
        m = models.convnext_tiny(weights=weights); m.classifier[2] = nn.Linear(m.classifier[2].in_features, n_classes)
    return m


def head_module(model: nn.Module, arch: str) -> nn.Module:
    """새로 단 분류 층 (learning rate 를 백본과 다르게 주려고 따로 잡는다)."""
    if arch.startswith("resnet"):
        return model.fc
    return model.classifier


def param_groups(model: nn.Module, arch: str):
    """(백본 파라미터, 헤드 파라미터)"""
    head = head_module(model, arch)
    head_ids = {id(p) for p in head.parameters()}
    backbone = [p for p in model.parameters() if id(p) not in head_ids]
    return backbone, list(head.parameters())


def cam_target_layer(model: nn.Module, arch: str) -> nn.Module:
    """Grad-CAM 을 걸 마지막 conv 블록."""
    if arch.startswith("resnet"):
        return model.layer4
    return model.features


def save_checkpoint(path: Path | str, model: nn.Module, meta: dict) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"format": CHECKPOINT_FORMAT, "meta": dict(meta), "state_dict": model.state_dict()}
    torch.save(payload, path)
    return path


def load_checkpoint(path: Path | str, device: str = "cpu"):
    """→ (model.eval(), meta). meta: arch · classes · img_size · mean · std · class_to_recipe · unknown_threshold …"""
    payload = torch.load(Path(path), map_location=device, weights_only=False)
    meta = payload["meta"]
    model = build_model(meta["arch"], len(meta["classes"]), pretrained=False)
    model.load_state_dict(payload["state_dict"])
    model.to(device).eval()
    return model, meta


def pick_device(name: str = "auto") -> str:
    if name != "auto":
        return name
    return "cuda" if torch.cuda.is_available() else "cpu"
