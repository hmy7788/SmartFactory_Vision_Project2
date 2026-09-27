# yuseong/web 변경 이력 (2026-09-22 ~ 09-27)

커밋 19개. 자동 테스트 44 → 104개 (전부 통과), 레시피 판정 매트릭스 53건 통과.
다시 확인: `python -m unittest discover -s tests` · `python -m scripts.check_recipes`

| 날짜 | 커밋 | 영역 | 무엇을 |
|---|---|---|---|
| 09-27 | (이 커밋) | 웹 | 작업 화면 완충(확정만 그림·재료 최빈값·HOLD 유예·칩 지연·진행 막대), `--video-end hold`(영상 끝 마지막 장면 유지) + reset 되감기, `tests/test_web_ui.js` |
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

## 09-27 작업 화면 완충 — "재료 확인과 오른쪽 OK/NG 가 계속 바뀐다"

- 문제: 실제 영상에서 검출이 프레임마다 조금씩 흔들리면 재료 표의 "있음" 칸, "X 1개 더 놓으세요", 오른쪽 카드가 같이 깜빡였다. 손이 Mother 를 잠깐 가리면 카드가 통째로 보류(잠깐)로 바뀌었다 돌아왔다.
- 원인: 화면이 후보(`candidate`, 매 프레임)와 원시 수량(`materials.observed`)을 그대로 그렸다. 코어는 안정화(재료 1000ms · 조립 400ms) 뒤에만 확정하지만, 화면은 확정 전 값을 다 보여 줬다. 코어는 HOLD 가 오면 `confirmed` 를 즉시 비운다 (설계상 맞음) → 화면도 즉시 바뀜.
- 수정 (`web/static/app.js`, `app.css` — 코어·파이프라인 판정은 그대로): 화면은 파생 상태만 그린다. ① 큰 글씨·NG 상세·자리 표 = 마지막 확정(`S.shown`), ② 재료 수량 = 최근 700ms 최빈값, ③ HOLD 는 1.5초 유예(마지막 확정을 흐리게 유지 + "확인 중"), ④ "확인 중" 칩은 600ms 지나야, ⑤ 확정까지 남은 시간 막대(재료 READY·조립 확정 전), ⑥ DOM 은 파생 상태가 바뀔 때만 다시 그림. 값은 `app.js` 의 `UI` 상수. 상세는 `docs/web.md` "작업 화면이 흔들리지 않게".
- "작업 완료가 안 뜬다": 원인 둘. (a) 박스가 그려진 `*_obb.mp4` 를 넣어 모델이 부품을 못 잡음 → 원본 영상 사용. (b) 영상이 끝나면 처음부터 반복돼 PASS 가 곧 사라짐 → `--video-end hold`(기본) 로 마지막 장면 유지, [작업 완료]/[새 작업] 이 되감기.
- 검증: `tests/test_web_ui.js` (node, 30 검사 — 흔들리는 payload 순서에 화면이 몇 번 다시 그려지는지), `test_video_end_hold_keeps_last_frame_and_reset_rewinds`. 전체 104개 통과 (1개 skip: ultralytics 없는 환경).

## 남은 문제

- 손이 가로바 끝을 가리면 박스가 짧아져 H 자리가 어긋남 → 가로바 폭 유지 규칙 필요 (팀 합의 후).
- ROI 실물 보정 전 (`calibration_status: UNVALIDATED_DEFAULTS`).
- 주황 볼트가 가장 약함 (AP50 0.949).
- 시연 노트북 CPU 속도 미측정 (`python -m src.detection.evaluate_obb --bench-only`).
