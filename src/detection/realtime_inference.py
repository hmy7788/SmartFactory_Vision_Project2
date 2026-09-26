"""YOLO-OBB 만 따로 눈으로 보는 창 — 웹캠·영상·사진 폴더. 코어·레시피 판정 없이 '무엇이 어디, 몇 도' 만 그린다. (ultralytics 필요)

    python -m src.detection.realtime_inference                       # 웹캠 0, model/yolo_obb_parts.pt
    python -m src.detection.realtime_inference --source 1 --imgsz 480 --skip 2      # CPU 노트북: 입력 줄이고 2프레임에 한 번 추론
    python -m src.detection.realtime_inference --source data\\dataset_obb\\images\\test   # 폴더 → runs/obb_infer/test/

레시피 대조·PASS/NG 까지 보려면 웹 화면(run_ui.cmd / run_live.cmd)을 쓴다 — 거기선 영상과 추론이 분리돼 있어 끊기지 않는다.
단축키: q/ESC 종료 · s 저장 (runs/snapshots/) · p 일시정지
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = ROOT / "model" / "yolo_obb_parts.pt"
COLORS = {"bolt_2": (0, 140, 255), "bolt_1": (0, 220, 220), "mother_part": (0, 200, 80), "part_3hole": (80, 180, 255), "part_2hole": (200, 80, 255)}


def load_names(model) -> dict[int, str]:
    """모델 이름 → 코어 이름(bolt_1 …). cv2 는 한글을 못 그리므로 영문으로 바꿔 둔다."""
    names = {int(i): str(n) for i, n in dict(model.names).items()}
    try:
        mapping = json.loads((ROOT / "config" / "class_mapping.json").read_text(encoding="utf-8"))
        names = {i: mapping.get(n, n) for i, n in names.items()}
    except (OSError, ValueError):
        pass
    return names


def draw(frame, result, names):
    import cv2
    import numpy as np
    from .obb_labels import long_axis_angle

    obb = getattr(result, "obb", None)
    if obb is None or len(obb) == 0:
        return frame, {}
    counts = {}
    corners_all = obb.xyxyxyxy.cpu().numpy()
    for corners, (cx, cy, w, h, ang), cid, conf in zip(corners_all, obb.xywhr.cpu().tolist(), obb.cls.cpu().tolist(), obb.conf.cpu().tolist()):
        name = names.get(int(cid), str(int(cid)))
        counts[name] = counts.get(name, 0) + 1
        color = COLORS.get(name, (200, 200, 200))
        cv2.polylines(frame, [corners.astype(np.int32).reshape(-1, 1, 2)], True, color, 2)
        theta = long_axis_angle(w, h, ang)                               # 코어가 쓰는 긴 변 방향
        L = 0.5 * max(w, h)
        cv2.line(frame, (int(cx - L * math.cos(theta)), int(cy - L * math.sin(theta))),
                 (int(cx + L * math.cos(theta)), int(cy + L * math.sin(theta))), color, 1, cv2.LINE_AA)
        label = f"{name} {conf:.2f} {math.degrees(theta):+.0f}deg"
        x0, y0 = int(corners[:, 0].min()), int(corners[:, 1].min())
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        y = y0 - 4 if y0 - th - 8 > 0 else y0 + th + 8
        cv2.rectangle(frame, (x0, y - th - 4), (x0 + tw + 6, y + base), color, -1)
        cv2.putText(frame, label, (x0 + 3, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return frame, counts


def hud(frame, fps, infer_ms, counts, paused):
    import cv2
    h, w = frame.shape[:2]
    ov = frame.copy(); cv2.rectangle(ov, (0, 0), (w, 30), (15, 15, 15), -1); cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
    txt = f"FPS {fps:4.1f}  infer {infer_ms:5.1f} ms  " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
    if paused:
        txt = "PAUSED (p to resume)   " + txt
    cv2.putText(frame, txt, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 255, 220), 1, cv2.LINE_AA)
    return frame


def run_folder(model, folder: Path, a, names):
    import cv2
    out = ROOT / "runs" / "obb_infer" / folder.name
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))
    for p in paths:
        img = cv2.imread(str(p))
        if img is None:
            continue
        r = model.predict(img, conf=a.conf, imgsz=a.imgsz, device=a.device, verbose=False)[0]
        vis, _ = draw(img, r, names)
        cv2.imwrite(str(out / p.name), vis)
    print(f"{len(paths)}장 → {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="YOLO-OBB 눈으로 보기")
    ap.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    ap.add_argument("--source", default="0", help="웹캠 번호 / 영상 파일 / 사진 폴더")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640, help="CPU 면 480 이 반 정도 빠르다")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--skip", type=int, default=1, help="N 프레임마다 한 번 추론 (그 사이는 마지막 결과를 그대로 그림)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    a = ap.parse_args(argv)

    import cv2
    try:
        from ultralytics import YOLO
    except ImportError:
        sys.exit("ultralytics 가 없습니다: pip install ultralytics")
    from .train_yolo_obb import pick_device
    a.device = pick_device(a.device)
    if not Path(a.weights).exists():
        sys.exit(f"가중치가 없습니다: {a.weights}   (먼저 python -m src.detection.train_yolo_obb)")
    model = YOLO(a.weights)
    if getattr(model, "task", None) != "obb":
        sys.exit(f"OBB 모델이 아닙니다 (task={getattr(model, 'task', None)}). 회전 없는 모델은 웹 화면의 --refine-angles 로 보세요.")
    names = load_names(model)

    src = Path(a.source)
    if src.is_dir():
        return run_folder(model, src, a, names)
    cap = cv2.VideoCapture(int(a.source)) if a.source.isdigit() else cv2.VideoCapture(str(src))
    if a.source.isdigit():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.width); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    if not cap.isOpened():
        sys.exit(f"소스를 열 수 없습니다: {a.source}")
    snap = ROOT / "runs" / "snapshots"; snap.mkdir(parents=True, exist_ok=True)
    fps_hist, paused, k, result, infer_ms, n_snap = [], False, 0, None, 0.0, 0
    prev = time.perf_counter()
    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok:
                break
            if k % max(1, a.skip) == 0:
                t = time.perf_counter()
                result = model.predict(frame, conf=a.conf, imgsz=a.imgsz, device=a.device, verbose=False)[0]
                infer_ms = (time.perf_counter() - t) * 1000
            k += 1
            vis, counts = draw(frame, result, names) if result is not None else (frame, {})
            now = time.perf_counter(); fps_hist.append(1 / max(now - prev, 1e-6)); prev = now
            fps_hist = fps_hist[-30:]
            vis = hud(vis, sum(fps_hist) / len(fps_hist), infer_ms, counts, paused)
        cv2.imshow("YOLO-OBB", vis)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("s"):
            p = snap / f"snap_{n_snap:04d}.jpg"; cv2.imwrite(str(p), vis); n_snap += 1; print(f"저장: {p}")
        if key == ord("p"):
            paused = not paused
    cap.release(); cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
