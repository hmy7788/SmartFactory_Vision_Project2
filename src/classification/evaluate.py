"""평가 — 체크포인트를 test 사진에 돌려 정확도·F1·confusion matrix 를 내고, Grad-CAM 그림을 만든다. (torch 필요)

    python -m src.classification.evaluate --weights weights\\classifier_resnet18.pt --data ..\\aabb
    python -m src.classification.evaluate --weights weights\\classifier_resnet18.pt --data ..\\aabb --split train
    python -m src.classification.evaluate --weights weights\\classifier_resnet18.pt --data ..\\aabb --gradcam 6

Grad-CAM: 마지막 conv 블록의 활성을 정답 클래스 점수의 기울기로 가중해 "어디를 보고 판정했나" 를 색으로 덮는다.
막대·볼트 위에 열이 모이면 형태를 보는 것이고, 배경에 모이면 배경을 외운 것이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .dataset import class_names, load_image, scan, split, summary
from .metrics import draw_confusion, markdown_table, report
from .predict import Classifier


def gradcam(clf: Classifier, image, target_index: int | None = None):
    """→ (heatmap[H,W] 0..1, 예측 index). 마지막 conv 블록에 hook 을 걸어 한 장씩 계산한다."""
    import torch
    from .model import cam_target_layer

    layer = cam_target_layer(clf.model, clf.meta["arch"])
    store = {}

    def fwd_hook(_, __, out): store["act"] = out; out.register_hook(lambda g: store.__setitem__("grad", g))

    h = layer.register_forward_hook(fwd_hook)
    try:
        x = clf.tf(load_image(image)).unsqueeze(0).to(clf.device)
        clf.model.zero_grad(set_to_none=True)
        with torch.enable_grad():
            logits = clf.model(x)
            idx = int(logits.argmax(1)) if target_index is None else target_index
            logits[0, idx].backward()
    finally:
        h.remove()
    act, grad = store["act"][0], store["grad"][0]                    # (C, h, w)
    weights = grad.mean(dim=(1, 2), keepdim=True)
    cam = torch.relu((weights * act).sum(0)).detach().cpu().numpy()
    cam = cam - cam.min(); cam = cam / (cam.max() + 1e-8)
    return cam, idx


def save_gradcam(clf: Classifier, image_path: Path, out_path: Path, true_label: str | None = None):
    """원본(letterbox) | 히트맵 덮은 그림 을 나란히 저장."""
    import cv2
    from .dataset import letterbox

    cam, idx = gradcam(clf, image_path)
    size = int(clf.meta["img_size"])
    base = np.array(letterbox(load_image(image_path), size))[:, :, ::-1].copy()      # RGB → BGR
    heat = cv2.resize((cam * 255).astype(np.uint8), (size, size))
    heat = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
    over = cv2.addWeighted(base, 0.55, heat, 0.45, 0)
    r = clf.predict(image_path)
    text = f"pred {r.label} {r.confidence:.2f}" + (f"  true {true_label}" if true_label else "") + ("  UNKNOWN" if r.unknown else "")
    color = (0, 200, 0) if (true_label is None or r.label == true_label) else (0, 0, 255)
    both = np.concatenate([base, over], axis=1)
    cv2.putText(both, text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(out_path.suffix or ".jpg", both)   # imwrite는 한글 경로에 못 쓴다
    if ok:
        buf.tofile(str(out_path))
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="완성 조립체 분류기 평가")
    ap.add_argument("--weights", default="weights/classifier_resnet18.pt")
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="test", choices=["test", "train", "all"])
    ap.add_argument("--report-dir", default="reports/classification")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--gradcam", type=int, default=0, help="Grad-CAM 그림 장수 (클래스별로 고르게, 틀린 것 우선)")
    a = ap.parse_args(argv)
    try:
        import torch  # noqa: F401
    except ImportError:
        sys.exit("torch 가 없습니다. install.cmd 로 먼저 설치하세요.")

    clf = Classifier.load(a.weights, a.device, a.threshold)
    samples = scan(a.data)
    if a.split != "all":
        samples = split(samples, a.split)
    if not samples:
        sys.exit(f"{a.data} 의 {a.split} 에 사진이 없습니다")
    unknown_cls = set(class_names(samples)) - set(clf.classes)
    if unknown_cls:
        sys.exit(f"체크포인트에 없는 클래스가 데이터에 있습니다: {sorted(unknown_cls)} (체크포인트: {clf.classes})")
    print(f"데이터 ({a.split}): {summary(samples) if a.split == 'all' else len(samples)}장   모델: {clf.meta['arch']} {clf.meta['img_size']}px   unknown<{clf.threshold}")

    results = clf.predict_batch([s.path for s in samples])
    index = {c: i for i, c in enumerate(clf.classes)}
    ys = [index[s.label] for s in samples]; ps = [index[r.label] for r in results]
    rep = report(ys, ps, clf.classes)
    rep["unknown_count"] = int(sum(r.unknown for r in results))
    rep["per_image"] = [{"file": s.path.name, "true": s.label, "pred": r.label, "conf": round(r.confidence, 4), "unknown": r.unknown,
                         "ok": s.label == r.label} for s, r in zip(samples, results)]

    report_dir = Path(a.report_dir); report_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{a.split}"
    (report_dir / f"eval_{tag}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / f"eval_{tag}.md").write_text(f"# {clf.meta['arch']} — {tag} {rep['n']}장\n\n" + markdown_table(rep) + "\n", encoding="utf-8")
    draw_confusion(rep, report_dir / f"confusion_{tag}.png", f"{clf.meta['arch']} {tag}")

    print(f"\naccuracy {rep['accuracy']:.3f}   macro F1 {rep['macro_f1']:.3f}   unknown {rep['unknown_count']}장\n")
    print(markdown_table(rep))
    wrong = [r for r in rep["per_image"] if not r["ok"]]
    if wrong:
        print("\n틀린 사진:")
        for r in wrong:
            print(f"  {r['file']:24} 정답 {r['true']:8} → 예측 {r['pred']:8} conf {r['conf']:.2f}")
    low = sorted(rep["per_image"], key=lambda r: r["conf"])[:3]
    print("\n확신이 낮은 사진 3장: " + ", ".join(f"{r['file']} {r['conf']:.2f}" for r in low))

    if a.gradcam:
        picks = [s for s, r in zip(samples, results) if s.label != r.label]
        for c in clf.classes:
            picks += [s for s in samples if s.label == c and s not in picks][: max(1, a.gradcam // len(clf.classes))]
        picks = picks[: max(a.gradcam, len(wrong))]
        for s in picks:
            save_gradcam(clf, s.path, report_dir / "gradcam" / f"{s.path.stem}.jpg", s.label)
        print(f"\nGrad-CAM {len(picks)}장 → {report_dir / 'gradcam'}/")
    print(f"\n보고서: {report_dir}/eval_{tag}.md, confusion_{tag}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
