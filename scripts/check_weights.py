"""받은 가중치(.pt)가 이 시스템에 맞는지 확인한다 — 카메라 없이, 파일 하나로.

    python -m scripts.check_weights weights/yolo_obb_parts.pt
    python -m scripts.check_weights weights/rtdetr_best.pt --model-type rtdetr

확인하는 것:
  1. ultralytics 로 열리는가 — YOLO(v8·11·26 …) 인지 RT-DETR 인지 자동 판별 (src/vision/model_loader.py)
  2. task 가 obb 또는 detect 인가 (detect=AABB 는 각도가 없어 UI 가 OpenCV 각도 보정을 자동으로 켠다)
  3. 클래스 이름이 코어 5클래스로 이어지는가 — 가중치 옆 <이름>.classes.json 또는 config/class_mapping.json
  4. scripts/sample_img/ 의 실제 사진 한 장으로 추론해서 뭐가 잡히는지 (3구 파트→Mother 오분류 같은 것)
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("weights", nargs="?", default=str(ROOT / "weights/yolo_obb_parts.pt"))
    ap.add_argument("--model-type", choices=["auto", "yolo", "rtdetr"], default="auto")
    ap.add_argument("--class-map", default=None)
    ap.add_argument("--imgsz", type=int, default=640)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    path = Path(a.weights)
    if not path.exists():
        print(f"파일이 없습니다: {path}"); return 1
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("ultralytics 가 없습니다 — pip install -r requirements-vision.txt 먼저"); return 1
    from src.vision.model_loader import check_names, load_mapping, load_model, resolve_mapping

    model, info = load_model(path, a.model_type)
    print(f"파일: {path}  ({info.size_mb} MB)")
    task_note = {"obb": "OK (회전 박스 — 각도까지 나옴)",
                 "detect": "OK (AABB — 각도 없음. UI 가 OpenCV 각도 보정을 자동으로 켭니다)"}
    print(f"종류: {info.kind}   task: {info.task}   {task_note.get(info.task, '!! obb 도 detect 도 아닙니다 — 이 시스템엔 못 씁니다')}")
    print(f"모델 클래스 {len(info.names)}개: {info.names}")
    mapping_path = resolve_mapping(path, a.class_map)
    print(f"매핑 파일: {mapping_path}")
    names_ok, lines = check_names(info.names, load_mapping(mapping_path))
    for line in lines:
        print("   " + line)

    sample = ROOT / "scripts/sample_img/material_sample_4.jpg"
    if info.task in ("obb", "detect") and sample.exists():
        print(f"\n추론 테스트: {sample.name} (정상 재료 4종이 다 있는 사진)")
        r = model.predict(str(sample), conf=0.25, imgsz=a.imgsz, verbose=False)[0]
        res = r.obb if info.task == "obb" else r.boxes
        if res is None or len(res) == 0:
            print("   검출 0개 — 조명·배경 차이거나 모델 문제")
        else:
            c = Counter(info.names[int(k)] for k in res.cls.cpu().tolist())
            confs = res.conf.cpu().tolist()
            print(f"   검출 {len(confs)}개: {dict(c)}   conf {min(confs):.2f}~{max(confs):.2f}")
            mapping = load_mapping(mapping_path)
            mothers = sum(n for name, n in c.items() if mapping.get(name, name) == "mother_part")
            if mothers > 1:
                print(f"   !! Mother 가 {mothers}개로 잡혔습니다 — 3구 파트를 Mother 로 보는 문제가 있을 수 있음 (코어는 MULTIPLE_MOTHERS 보류)")
    ok = info.task in ("obb", "detect") and names_ok
    print("\n" + ("=== 이 가중치로 UI 를 돌릴 수 있습니다. run_ui.cmd (또는 python -m scripts.run_ui) 로 띄우세요." if ok
                  else "=== 위 항목을 고친 뒤 다시 확인하세요."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
