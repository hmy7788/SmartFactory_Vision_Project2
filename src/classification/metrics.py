"""정확도 · 클래스별 precision/recall/F1 · confusion matrix — numpy 만 쓴다 (PC 에 sklearn 없어도 됨)."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def confusion_matrix(y_true, y_pred, n_classes: int) -> np.ndarray:
    """행 = 정답, 열 = 예측."""
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for t, p in zip(y_true, y_pred):
        cm[int(t), int(p)] += 1
    return cm


def report(y_true, y_pred, classes: list[str]) -> dict:
    cm = confusion_matrix(y_true, y_pred, len(classes))
    n = int(cm.sum())
    per_class = {}
    f1s = []
    for i, c in enumerate(classes):
        tp = int(cm[i, i]); fp = int(cm[:, i].sum() - tp); fn = int(cm[i, :].sum() - tp)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_class[c] = {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4), "support": int(cm[i, :].sum())}
        f1s.append(f1)
    return {
        "n": n,
        "accuracy": round(float(np.trace(cm) / n), 4) if n else 0.0,
        "macro_f1": round(float(np.mean(f1s)), 4) if f1s else 0.0,
        "per_class": per_class,
        "confusion": cm.tolist(),
        "classes": list(classes),
    }


def markdown_table(rep: dict) -> str:
    """발표 자료에 붙여 넣을 표."""
    lines = ["| 클래스 | precision | recall | F1 | 장수 |", "|---|---|---|---|---|"]
    for c, m in rep["per_class"].items():
        lines.append(f"| {c} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {m['support']} |")
    lines.append(f"| **전체** | | accuracy {rep['accuracy']:.3f} | macro F1 {rep['macro_f1']:.3f} | {rep['n']} |")
    cm = rep["confusion"]; cl = rep["classes"]
    lines += ["", "Confusion matrix (행 = 정답, 열 = 예측)", "", "| | " + " | ".join(f"→ {c}" for c in cl) + " |", "|---|" + "---|" * len(cl)]
    for c, row in zip(cl, cm):
        lines.append(f"| {c} | " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def draw_confusion(rep: dict, path: Path | str, title: str = "Confusion matrix") -> Path:
    """PIL 로 그린 confusion matrix 그림 (matplotlib 없이)."""
    from PIL import Image, ImageDraw, ImageFont

    cm = np.array(rep["confusion"]); cl = rep["classes"]; k = len(cl)
    cell, left, top = 110, 150, 70
    W, H = left + cell * k + 20, top + cell * k + 20
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=18); small = ImageFont.load_default(size=14)
    except TypeError:                                     # 옛 Pillow
        font = small = ImageFont.load_default()
    vmax = max(1, cm.max())
    d.text((left, 12), f"{title} — acc {rep['accuracy']:.3f}", fill="black", font=font)
    for i in range(k):
        d.text((8, top + i * cell + cell // 2 - 8), cl[i], fill="black", font=small)
        d.text((left + i * cell + 6, top - 24), cl[i], fill="black", font=small)
        for j in range(k):
            v = int(cm[i, j]); t = v / vmax
            color = (int(255 - 190 * t), int(255 - 150 * t), 255) if i == j else (255, int(255 - 200 * t), int(255 - 200 * t))
            if v == 0: color = (245, 245, 245)
            x0, y0 = left + j * cell, top + i * cell
            d.rectangle([x0, y0, x0 + cell - 2, y0 + cell - 2], fill=color, outline="gray")
            d.text((x0 + cell // 2 - 8, y0 + cell // 2 - 10), str(v), fill="black", font=font)
    d.text((8, top + k * cell + 2), "행 = 정답, 열 = 예측", fill="gray", font=small)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
