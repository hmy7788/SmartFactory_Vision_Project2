# 모델 가중치 안내

**모든 `.pt` 파일은 이 폴더(`weights/`) 하나로 통일한다.** (2026-10-02 정리 — 이전엔 `model/`, `checkpoints/`, 저장소 루트에 흩어져 있었음)
`*.pt`는 Git에서 제외된다(`.gitignore`). 가중치 없이도 코어 테스트/합성 데모는 실행할 수 있다.

## 현재 파일

| 파일 | 역할 |
|---|---|
| `yolo_obb_parts.pt` | 메인 파이프라인(YOLO11n-OBB) 학습 완료 가중치 — 라이브 검사 기본값(`--model-type yolo-obb`) |
| `yolo26_obb_parts_50.pt` | YOLO26n-OBB 학습 완료 가중치 (비교 실험용) |
| `yolo26n.pt` | YOLO26n 사전학습 베이스 체크포인트 (COCO, fine-tuning 전 원본 — 프로젝트 모델 아님) |
| `yolo11n-obb.pt` | YOLO11n-OBB 사전학습 베이스 체크포인트 (`train_yolo_obb.py` 기본 `--model`) |
| `rtdetr-l.pt` | RT-DETR-L 사전학습 베이스 체크포인트 (`train_rtdetr.py` 기본 `--model`) |

학습 스크립트(`src/detection/yolo11/train_yolo_obb.py`, `src/detection/rt-detr/train_rtdetr.py`)는 학습이 끝나면
최종 가중치를 자동으로 이 폴더에 복사한다 — `runs/`(Ultralytics 자체 학습 로그·plot) 안을 뒤질 필요 없음.

클래스: 볼트_주황, 볼트_노랑, 나무_5구멍, 나무_3구멍, 나무_2구멍. `config/class_mapping.json`으로 내부 이름을 연결한다.

⚠️ 모델 교체 시 버전/해시를 기록하고 샘플을 재검증한다. 과거 중간 학습본의 3구→Mother 혼동 이력은 `docs/validation_2026-09-22.md` 참고.
