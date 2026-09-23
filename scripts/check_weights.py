"""받은 가중치(.pt)가 이 시스템에 맞는지 확인한다 — 카메라 없이, 파일 하나로.

    python -m scripts.check_weights model/yolo_obb_parts.pt

확인하는 것:
  1. ultralytics 로 열리는가
  2. task 가 obb 또는 detect 인가 (detect=AABB 는 각도가 없어 똑바로 놓는 시연만 됨; 삐뚤게는 --refine-angles)
  3. 클래스 이름이 config/class_mapping.json 의 왼쪽(모델 이름) 또는 오른쪽(우리 이름)과 맞는가
  4. sample_img/ 의 실제 사진 한 장으로 추론해서 뭐가 잡히는지 (3구 파트→Mother 오분류 같은 것)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else ROOT / "model/yolo_obb_parts.pt"
    if not path.exists():
        print(f"파일이 없습니다: {path}"); return 1
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics 가 없습니다 — install.cmd 먼저"); return 1

    print(f"파일: {path}  ({path.stat().st_size / 1e6:.1f} MB)")
    model = YOLO(str(path))
    task = getattr(model, "task", None)
    names = dict(model.names) if hasattr(model, "names") else {}
    task_note = {"obb": "OK (회전 박스 — 각도까지 나옴)",
                 "detect": "OK (AABB — 각도 없음. 똑바로 놓는 시연은 그대로, 삐뚤게는 run_live 의 --refine-angles)"}
    print(f"task: {task}   {task_note.get(task, '!! obb 도 detect 도 아닙니다 — 이 시스템엔 못 씁니다')}")
    print(f"클래스 {len(names)}개: {names}")

    mapping = json.loads((ROOT / "config/class_mapping.json").read_text(encoding="utf-8"))
    model_names = set(names.values())
    canonical = set(mapping.values())                    # 우리 이름(bolt_1 …)을 모델이 바로 내면 매핑 없이 통과
    missing = sorted(set(mapping) - model_names)          # 매핑엔 있는데 모델에 없는 이름
    extra = sorted(model_names - set(mapping))            # 모델엔 있는데 매핑에 없는 이름
    if model_names == canonical:
        print(f"클래스 이름: 우리 이름 그대로 ({sorted(canonical)})  OK"); missing = extra = []
    elif not missing and not extra:
        print("매핑: 5/5 일치  OK")
    else:
        print("매핑: 불일치")
        if extra:
            print(f"   모델이 내는 이름인데 class_mapping.json 에 없음: {extra}")
        if missing:
            print(f"   class_mapping.json 에는 있는데 모델에 없음: {missing}")
        print("   → config/class_mapping.json 의 왼쪽 이름을 모델 이름으로 바꾸면 됩니다 (오른쪽은 그대로).")
        if len(extra) == len(missing) == 5:
            print("   예:", {e: mapping[m] for e, m in zip(extra, missing)})

    sample = ROOT / "sample_img/material_sample_4.jpg"
    if task in ("obb", "detect") and sample.exists():
        print(f"\n추론 테스트: {sample.name} (정상 재료 4종이 다 있는 사진)")
        r = model.predict(str(sample), conf=0.25, imgsz=640, verbose=False)[0]
        res = r.obb if task == "obb" else r.boxes
        if res is None or len(res) == 0:
            print("   검출 0개 — 조명·배경 차이거나 모델 문제")
        else:
            from collections import Counter
            c = Counter(names[int(k)] for k in res.cls.cpu().tolist())
            confs = res.conf.cpu().tolist()
            print(f"   검출 {len(confs)}개: {dict(c)}   conf {min(confs):.2f}~{max(confs):.2f}")
            mother_name = "mother_part" if "mother_part" in names.values() else next((k for k, v in mapping.items() if v == "mother_part"), None)
            if mother_name and c.get(mother_name, 0) > 1:
                print(f"   !! Mother 가 {c[mother_name]}개로 잡혔습니다 — 3구 파트를 Mother 로 보는 문제가 아직 있을 수 있음 (코어는 MULTIPLE_MOTHERS 보류)")
    ok = task in ("obb", "detect") and not missing and not extra
    print("\n" + ("=== 이 가중치로 시연 가능합니다. run_live.cmd 로 띄우세요." if ok else "=== 위 항목을 고친 뒤 다시 확인하세요."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
