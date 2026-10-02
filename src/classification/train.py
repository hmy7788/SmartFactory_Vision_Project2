"""학습 — ImageNet 사전학습 CNN 을 완성체 사진 3 클래스에 맞춘다. (torch 필요)

    python -m src.classification.train --data ..\\aabb --out weights\\classifier_resnet18.pt
    python -m src.classification.train --data ..\\aabb --arch convnext_tiny --out weights\\classifier_convnext.pt
    python -m src.classification.train --smoke                      # 가짜 데이터로 파이프라인만 20초 확인
    python -m src.classification.train --data ..\\aabb --cv 5       # 5-fold 로 정확도 분산까지 (체크포인트 안 만듦)

두 단계로 학습한다:
    1) 백본 동결, 새 분류 층만 학습 (freeze-epochs)  — 사전학습 특징을 망치지 않고 헤드를 자리 잡게
    2) 전체 풀고 백본은 작은 LR, 헤드는 큰 LR (나머지 epoch, cosine 감쇠)
epoch 수는 고정이다. test 로 early stopping 을 하면 test 가 검증셋이 돼 버린다 (CLAUDE.md: Val 없이 Train/Test).
test 정확도는 epoch 마다 찍지만 기록용이지 선택 기준이 아니다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .dataset import class_names, load_settings, make_torch_dataset, scan, split, summary, IMAGENET_MEAN, IMAGENET_STD
from .metrics import draw_confusion, markdown_table, report


def seed_all(seed: int):
    import torch
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)


def class_weights(labels: list[str], classes: list[str]):
    """적은 클래스(model_a 17장)에 가중치를 더 준다: n_total / (n_classes · n_c)."""
    import torch
    c = Counter(labels); n = len(labels)
    return torch.tensor([n / (len(classes) * max(1, c[k])) for k in classes], dtype=torch.float32)


def run_epoch(model, loader, device, criterion, optimizer=None):
    """optimizer 가 있으면 학습, 없으면 평가. → (loss, acc, y_true, y_pred)"""
    import torch
    training = optimizer is not None
    model.train(training)
    tot_loss, ys, ps = 0.0, [], []
    with torch.set_grad_enabled(training):
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = criterion(logits, y)
            if training:
                optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
            tot_loss += float(loss) * len(y)
            ys += y.tolist(); ps += logits.argmax(1).tolist()
    n = max(1, len(ys))
    acc = float(np.mean(np.array(ys) == np.array(ps))) if ys else 0.0
    return tot_loss / n, acc, ys, ps


def fit(train_samples, test_samples, classes, a, device, log=print):
    """한 번 학습해서 (model, history, test_report) 를 돌려준다. --cv 에서도 그대로 쓴다."""
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from .model import build_model, param_groups

    ds_train = make_torch_dataset(train_samples, classes, a.img, train=True)
    ds_test = make_torch_dataset(test_samples, classes, a.img, train=False)
    # 마지막 배치가 1장이면 BatchNorm 이 학습 모드에서 죽는다 → 그 경우만 버린다
    dl_train = DataLoader(ds_train, batch_size=a.batch, shuffle=True, num_workers=a.workers, drop_last=(len(ds_train) % a.batch == 1))
    dl_test = DataLoader(ds_test, batch_size=a.batch, shuffle=False, num_workers=a.workers)

    model = build_model(a.arch, len(classes), pretrained=not a.no_pretrained).to(device)
    backbone, head = param_groups(model, a.arch)
    criterion = nn.CrossEntropyLoss(weight=class_weights([s.label for s in train_samples], classes).to(device),
                                    label_smoothing=a.label_smoothing)
    history = []
    t0 = time.time()

    def evaluate():
        if not test_samples:
            return None
        loss, acc, ys, ps = run_epoch(model, dl_test, device, criterion)
        return {"loss": round(loss, 4), "acc": round(acc, 4), "ys": ys, "ps": ps}

    # 1단계 — 백본 동결
    for p in backbone: p.requires_grad_(False)
    opt = torch.optim.AdamW(head, lr=a.lr, weight_decay=1e-4)
    for ep in range(a.freeze_epochs):
        loss, acc, _, _ = run_epoch(model, dl_train, device, criterion, opt)
        ev = evaluate()
        history.append({"epoch": len(history) + 1, "phase": "head", "train_loss": round(loss, 4), "train_acc": round(acc, 4),
                        "test_loss": ev and ev["loss"], "test_acc": ev and ev["acc"]})
        log(f"  [{len(history):2d}/{a.epochs}] head    loss {loss:.3f} acc {acc:.3f}" + (f"   test acc {ev['acc']:.3f}" if ev else "") + f"   {time.time() - t0:5.0f}s")
    # 2단계 — 전체 파인튜닝
    for p in backbone: p.requires_grad_(True)
    rest = max(0, a.epochs - a.freeze_epochs)
    opt = torch.optim.AdamW([{"params": backbone, "lr": a.backbone_lr}, {"params": head, "lr": a.lr}], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, rest))
    for ep in range(rest):
        loss, acc, _, _ = run_epoch(model, dl_train, device, criterion, opt)
        sched.step()
        ev = evaluate()
        history.append({"epoch": len(history) + 1, "phase": "full", "train_loss": round(loss, 4), "train_acc": round(acc, 4),
                        "test_loss": ev and ev["loss"], "test_acc": ev and ev["acc"]})
        log(f"  [{len(history):2d}/{a.epochs}] full    loss {loss:.3f} acc {acc:.3f}" + (f"   test acc {ev['acc']:.3f}" if ev else "") + f"   {time.time() - t0:5.0f}s")

    ev = evaluate()
    rep = report(ev["ys"], ev["ps"], classes) if ev else None
    return model, history, rep


def stratified_folds(samples, k: int, seed: int):
    """클래스별로 섞어 k 개 fold 로 나눈다 → [(train, test), …]"""
    rng = random.Random(seed)
    by = {}
    for s in samples: by.setdefault(s.label, []).append(s)
    folds = [[] for _ in range(k)]
    for label, items in sorted(by.items()):
        items = items[:]; rng.shuffle(items)
        for i, s in enumerate(items): folds[i % k].append(s)
    return [( [s for j, f in enumerate(folds) if j != i for s in f], folds[i]) for i in range(k)]


def parse(argv=None):
    st = load_settings()
    ap = argparse.ArgumentParser(description="완성 조립체 분류기 학습")
    ap.add_argument("--data", help="aabb 폴더 (images/train, images/test) 또는 클래스 폴더식 루트")
    ap.add_argument("--out", default="weights/classifier_resnet18.pt")
    ap.add_argument("--report-dir", default="reports/classification")
    ap.add_argument("--arch", default=st["arch"], help="resnet18 | resnet34 | efficientnet_b0 | mobilenet_v3_small | convnext_tiny")
    ap.add_argument("--img", type=int, default=int(st["img_size"]), help="입력 한 변 (정사각형 letterbox)")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--freeze-epochs", type=int, default=5, help="처음 몇 epoch 은 백본을 동결")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-3, help="분류 층 LR")
    ap.add_argument("--backbone-lr", type=float, default=1e-4, help="백본 LR (2단계)")
    ap.add_argument("--label-smoothing", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=0, help="DataLoader 워커 (윈도우는 0 권장)")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-pretrained", action="store_true", help="ImageNet 가중치 없이 (smoke 용)")
    ap.add_argument("--cv", type=int, default=0, help="k-fold 교차검증 (train+test 전부 섞어 k 번 학습). 체크포인트는 안 만든다")
    ap.add_argument("--smoke", action="store_true", help="가짜 데이터로 파이프라인만 확인")
    a = ap.parse_args(argv)
    if not a.smoke and not a.data:
        ap.error("--data 가 필요합니다 (또는 --smoke)")
    return a, st


def main(argv=None):
    a, st = parse(argv)
    try:
        import torch
    except ImportError:
        sys.exit("torch 가 없습니다. install.cmd 로 torch/torchvision 을 먼저 설치하세요.")
    from .model import pick_device, save_checkpoint

    tmp = None
    if a.smoke:
        from .synthetic import make_dataset
        tmp = tempfile.TemporaryDirectory()
        a.data = make_dataset(tmp.name, per_class_train=6, per_class_test=2, seed=a.seed)
        a.img, a.epochs, a.freeze_epochs, a.batch, a.no_pretrained = min(a.img, 96), 2, 1, 8, True
        a.out = str(Path(tmp.name) / "smoke.pt"); a.report_dir = str(Path(tmp.name) / "report")
        print("smoke: 가짜 데이터로 2 epoch (ImageNet 가중치 없이)")

    seed_all(a.seed)
    device = pick_device(a.device)
    samples = scan(a.data)
    if not samples:
        sys.exit(f"{a.data} 에서 model_*.png 같은 사진을 못 찾았습니다 (images/train, images/test 또는 train/<클래스>/ 모양이어야 함)")
    classes = class_names(split(samples, "train"))
    missing = set(class_names(split(samples, "test"))) - set(classes)
    if missing:
        sys.exit(f"test 에만 있는 클래스: {sorted(missing)} — train 에도 있어야 합니다")
    report_dir = Path(a.report_dir); report_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(report_dir / "train_log.txt", "a", encoding="utf-8")

    def log(msg=""):
        print(msg); log_file.write(msg + "\n"); log_file.flush()

    log(f"\n=== {time.strftime('%Y-%m-%d %H:%M')}  {' '.join(sys.argv[1:]) if argv is None else ' '.join(argv)}")
    log(f"데이터: {summary(samples)}")
    log(f"클래스: {classes}   장치: {device}   torch {torch.__version__}   arch: {a.arch}   입력: {a.img}px   epoch: {a.epochs} (동결 {a.freeze_epochs})")

    meta_base = {"arch": a.arch, "classes": classes, "img_size": a.img, "mean": list(IMAGENET_MEAN), "std": list(IMAGENET_STD),
                 "class_to_recipe": {c: st["class_to_recipe"].get(c) for c in classes},
                 "unknown_threshold": float(st["unknown_threshold"]), "seed": a.seed,
                 "train": {"epochs": a.epochs, "freeze_epochs": a.freeze_epochs, "batch": a.batch, "lr": a.lr,
                           "backbone_lr": a.backbone_lr, "label_smoothing": a.label_smoothing, "pretrained": not a.no_pretrained}}
    if a.cv:
        accs, f1s = [], []
        for i, (tr, te) in enumerate(stratified_folds(samples, a.cv, a.seed)):
            log(f"\n── fold {i + 1}/{a.cv}: train {len(tr)} / test {len(te)}")
            seed_all(a.seed + i)
            _, _, rep = fit(tr, te, classes, a, device, log)
            accs.append(rep["accuracy"]); f1s.append(rep["macro_f1"])
            log(f"   fold {i + 1} acc {rep['accuracy']:.3f}  macro F1 {rep['macro_f1']:.3f}")
        out = {"k": a.cv, "acc": accs, "macro_f1": f1s, "acc_mean": round(float(np.mean(accs)), 4), "acc_std": round(float(np.std(accs)), 4),
               "f1_mean": round(float(np.mean(f1s)), 4), "f1_std": round(float(np.std(f1s)), 4), "meta": meta_base}
        (report_dir / f"cv{a.cv}_{a.arch}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"\n{a.cv}-fold: accuracy {out['acc_mean']:.3f} ± {out['acc_std']:.3f}   macro F1 {out['f1_mean']:.3f} ± {out['f1_std']:.3f}")
        log_file.close()
        return 0

    model, history, rep = fit(split(samples, "train"), split(samples, "test"), classes, a, device, log)
    meta = dict(meta_base, history=history, test=rep, trained_at=time.strftime("%Y-%m-%d %H:%M"), n_train=len(split(samples, "train")))
    path = save_checkpoint(a.out, model, meta)
    (report_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    if rep:
        (report_dir / "metrics.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        (report_dir / "report.md").write_text(f"# {a.arch} — test {rep['n']}장\n\n" + markdown_table(rep) + "\n", encoding="utf-8")
        draw_confusion(rep, report_dir / "confusion.png", f"{a.arch} test")
        log(f"\ntest {rep['n']}장: accuracy {rep['accuracy']:.3f}   macro F1 {rep['macro_f1']:.3f}")
        log(markdown_table(rep))
    log(f"\n저장: {path}   보고서: {report_dir}/")
    log_file.close()
    if tmp:
        print("smoke OK — 파이프라인이 끝까지 돕니다.")
        tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
