# yuseong/web 변경 이력 (2026-09-22 ~ 09-27)

커밋 18개. 자동 테스트 44 → 102개 (전부 통과), 레시피 판정 매트릭스 53건 통과.
다시 확인: `python -m unittest discover -s tests` · `python -m scripts.check_recipes`

| 날짜 | 커밋 | 영역 | 무엇을 |
|---|---|---|---|
| 09-27 | e7aa0b9 | 코어 | 파트가 Mother 위·아래 어느 쪽으로 뻗어도 자리 판정 (`part_rois_down`, 앵커 탐색 방향) |
| 09-27 | 455a5e8 | 웹·뷰어 | 웹 UI `--video`, OBB 뷰어 `--save/--no-window`, `run_video.cmd`, `save_video_obb.cmd` |
| 09-27 | ce4b736 | 시연 | `setup_laptop.cmd`, `run_demo.cmd` (내장 웹캠 + OBB) |
| 09-26 | a849978 | 학습 | `train_obb_batch8.cmd` (4GB GPU) |
| 09-26 | 19d75d4 | 학습 | `install_torch_gpu.cmd` |
| 09-26 | be9d95a | YOLO-OBB | 데이터셋·학습·평가(mAP+각도+CPU 속도)·뷰어, `docs/detection_obb.md` |
| 09-23 | c7b66e4 | 웹 | 영상과 추론 분리 (최신 프레임만 추론) |
| 09-23 | 0e4ba1e | 비전 | AABB 모델 수용, `--refine-angles`, `replay_photos` |
| 09-23 | e0bd7d7 | 분류 | ResNet-18 트랙, `docs/classification.md` |
| 09-23 | 26b72ae | 스크립트 | `check_weights.py` |
| 09-23 | d342d67 | 웹 | `list_cameras.py`, DSHOW |
| 09-23 | b6aea81 | 웹 | `--no-model` |
| 09-23 | 111b805 | 스크립트 | `check_recipes.py` 판정 매트릭스 |
| 09-23 | ebb4513 | 웹 | 실제 `CameraSource` |
| 09-23 | 62d5700 | 웹 | 레시피 핫 추가 |
| 09-23 | 1b0a836 | 웹 | 작은 화면 레이아웃 |
| 09-22 | cb60a57 | 웹 | 작업자 화면 + 탭, demo/jsonl/camera 소스 |
| 09-22 | 3b497e2 | 저장 | SQLite 이벤트 저장소, `docs/storage.md` |

## 09-27 판정 코어 수정 — 파트 아래쪽 배치

- 문제: 팀원 시연 영상(recipe_3)에서 세로바를 가로바 아래로 바르게 끼웠는데 "어느 구멍인지 불명확" 으로 PASS 가 안 남.
- 원인: 파트 ROI 가 Mother-local 위쪽(-v)에만 있었고, 파트의 가로바 쪽 끝도 아래 방향으로만 찾음 → 아래쪽 파트는 `ambiguous`.
- 수정: `build_geometry` 가 `part_rois`(위) + `part_rois_down`(아래, 거울) 두 벌을 만들고, `associate` 가 파트 중심이 있는 쪽의 ROI 와 가로바 쪽 탐색 방향을 쓴다. `part_side()` 추가.
- 불변: 구멍 번호(H1~H5, 화면 왼쪽부터), 레시피, 볼트 판정, 파트 각도 ±20°, Mother 각도 ±15°, 안정화 시간. 기존 시나리오 42건 결과 동일.
- 검증: 시나리오 +11건(아래쪽 PASS, 위·아래 섞음 PASS, 아래쪽 종류 틀림 NG, 아래쪽 25° NG), 단위 테스트 +4.

## 남은 문제

- 손이 가로바 끝을 가리면 박스가 짧아져 H 자리가 어긋남 → 가로바 폭 유지 규칙 필요 (팀 합의 후).
- ROI 실물 보정 전 (`calibration_status: UNVALIDATED_DEFAULTS`).
- 주황 볼트가 가장 약함 (AP50 0.949).
- 시연 노트북 CPU 속도 미측정 (`python -m src.detection.evaluate_obb --bench-only`).
