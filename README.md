# SmartFactory Vision — 조립 실시간 검사 (Mother 등록 방식)

YOLO-OBB로 부품을 검출하고 **재료 확인 → Mother 등록 → 조립 검사** 순서로, 작업자가 레시피대로 조립하는지 실시간으로 확인한다. 잘못 끼우면 어느 구멍에 무엇이 틀렸는지 한글 메시지로 바로 알려준다.

`seungjae/state_machine` 브랜치(재료 확인 + Mother 기준 ROI 조립 검사)를 기반으로 Mother 등록, 가림 대응, 실시간 화면을 추가한 브랜치다.

## 공정 흐름

| 단계 | 작업자 | 시스템 | 다음 단계 조건 |
|---|---|---|---|
| 1. 재료 확인 `CHECK_MATERIALS` | 레시피 재료를 화면에 펼침 | 화면 전체 종류별 수량 비교 | 정확한 구성 1초 유지 |
| 2. Mother 등록 `REGISTER_MOTHER` | Mother만 가로로(구멍 5개 위로) 두고 손을 뗌 | 구멍 5개 실측 후 좌표 잠금 | 조건 만족 1초 유지 |
| 3. 조립 검사 `ASSEMBLING` | 레시피대로 볼트·나무조각 조립 | 구멍별 레시피 비교, 오류 즉시 표시 | 모두 맞으면 PASS |

- 단계는 뒤로 가지 않는다. 새 제품, 레시피 변경, 재등록 때만 되돌린다.
- 조립 순서는 자유. 부족은 `IN_PROGRESS`(노랑 안내), 잘못된 부품·위치·방향은 `NG`(빨강).
- 등록 거부: 옆면(구멍 2개)이 보임, 2구/3구 나무조각, 세로 배치(±15° 초과), Mother 위에 부품이 있음.
- 등록 후에는 잠근 좌표를 써서 손에 Mother가 가려져도 판정을 계속한다. Mother를 밀면 1초 뒤 다시 잠근다.
- 레시피대로 끼운 부품이 손에 가려지면 1.5초 동안 기억한다(화면 `H1*`). 잘못 끼운 부품은 기억하지 않아 빼면 NG가 바로 풀린다.
- 어느 구멍에도 맞지 않는 부품이 Mother 위에 1초 넘게 있으면 보라색 `?`와 메시지를 띄운다. 이때도 나머지 구멍 판정은 계속된다.

| Recipe | 요구 조립 (H1 = 화면 왼쪽, 순서 자유) |
|---|---|
| recipe_1 | H1 노랑 볼트(bolt_1) + 2구, H4 주황 볼트(bolt_2) + 3구 |
| recipe_2 | H1, H3 각각 노랑 볼트 + 2구 |
| recipe_3 | H2 주황 볼트 + 3구 |

## 설치

Python 3.10 이상(3.11 권장). 모든 명령은 저장소 루트에서 실행한다.

```powershell
git clone --branch taein/mother-registration --single-branch https://github.com/hmy7788/SmartFactory_Vision_Project2.git
cd SmartFactory_Vision_Project2
# (새 환경 + GPU) torch를 CUDA 버전에 맞게 먼저 설치
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
```

**모델 가중치는 Git에 없다(`*.pt` 제외).** 팀에서 받은 `yolo26_obb_parts.pt`를 `checkpoints/`에 넣는다. 스크립트가 아래 순서로 자동으로 찾고, 찾은 경로를 실행 첫 줄(`weights: ...`)에 출력한다.

1. `checkpoints/yolo26_obb_parts.pt`
2. `model/yolo_obb_parts.pt`
3. 위 두 경로를 상위 폴더 1~2단계에서

다른 가중치는 `--weights 경로`로 지정한다. 모델 클래스는 `bolt_1`(노랑), `bolt_2`(주황), `mother_part`, `part_2hole`, `part_3hole`. 한글 클래스 모델은 `config/class_mapping.json`으로 변환된다.

## 실행

```powershell
# 전체 흐름 (웹캠 2번, GPU)
python -m scripts.live_inspection --recipe recipe_1 --source 2 --device 0

# Mother 등록만 테스트
python -m scripts.live_registration --source 2 --device 0

# 사진 폴더로 등록 확인 → outputs/registration_debug/
python -m scripts.check_registration --images sample_img

# 모델 없이 합성 데모
python -m scripts.replay_detections --demo --recipe recipe_1
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--recipe` | recipe_1 | 시작 레시피 (실행 중 키로 변경 가능) |
| `--source` | 0 | 웹캠 번호 / 영상 파일 / 이미지 |
| `--device` | cpu | GPU는 `0` |
| `--weights` | 자동 탐색 | 가중치 경로 |
| `--max-frame-gap-ms` | 설정값 250 | CPU처럼 추론이 느릴 때 `500` |

`live_inspection` 키 (검사 창을 클릭한 뒤): `1`/`2`/`3` 레시피 변경(처음부터) · `n` 새 제품 · `r` Mother 재등록 · `s` 화면 저장 · `q` 종료.
상태가 바뀔 때마다 이벤트가 `outputs/live_inspection/events_*.jsonl`에 기록된다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

71개: 기존 MVP 흐름 44개, Mother 등록/추적 15개, 등록 포함 전체 흐름 12개.

## 폴더 구조

```
config/
  mvp.json                 판정 설정 (registration 블록 포함)
  class_mapping.json       한글 클래스 → 영문
  recipes/recipe_1~3.json  레시피
src/
  app/        inspection_service.py   프레임 처리·단계 흐름 (update(frame, image))
              config.py               설정 검증
              messages.py             작업자용 한글 메시지
  contracts/  detections.py, inspection.py    입력/출력 형식 (Phase, Status, Snapshot)
  geometry/   mother_registration.py  Mother 등록·추적 (좌표 잠금/재잠금)
              roi_builder.py          구멍별 Bolt/Part ROI
              association.py          부품 → 구멍 연결
              mother_frame.py, spatial.py
  process/    state_machine.py, evaluator.py, materials.py,
              occlusion.py (가림 기억), temporal.py, recipe.py
  vision/     detection_adapter.py    YOLO 결과 → DetectionFrame
              hole_detector.py        Mother 구멍 5개 실측 (OpenCV)
scripts/      live_inspection.py, live_registration.py, check_registration.py,
              replay_detections.py, demo_data.py, verify_materials.py, visualize_rois.py
tests/        test_mvp.py, test_material_workflow.py,
              test_mother_registration.py, test_registered_flow.py
docs/         mother_registration.md (이번 기능 상세), state_machine_handoff.md
checkpoints/  모델 가중치 (Git 제외)
outputs/      실행 결과 (Git 제외)
```

## 주요 설정 (`config/mvp.json`)

| 키 | 기본값 | 의미 |
|---|---|---|
| `confidence_threshold` | 0.5 | 이보다 낮은 검출은 판정에 쓰지 않음 |
| `stable_duration_ms` | 400 | 조립 판정 확정 시간 |
| `material_stable_duration_ms` | 1000 | 재료 확인 확정 시간 |
| `max_frame_gap_ms` | 250 | 프레임 간격이 이보다 길면 판정 대기 |
| `max_mother_angle_deg` | 15 | Mother 허용 기울기 |
| `part_rois` | 2구 0.48/0.14, 3구 0.70/0.28 | 나무조각 길이 / 구멍에서 중심까지 (Mother 길이 비율, 사진 실측) |
| `registration.enabled` | true | false면 기존 흐름 (재료 확인 → 바로 조립, 매 프레임 비율 계산) |
| `registration.register_stable_ms` | 1000 | 등록까지 손 뗀 채 기다리는 시간 |
| `registration.occlusion_hold_ms` | 1500 | 가려진 부품 기억 시간 |
| `registration.ambiguous_report_ms` | 1000 | 위치가 애매한 부품 메시지까지 걸리는 시간 |
| `registration.hole_min_contrast` | 0.45 | 구멍이 보인다고 판단하는 어두움 기준 |
| `registration.move_confirm_ms` | 1000 | Mother 이동 확정 시간 |
| `registration.lost_hold_ms` | 3000 | Mother가 이 시간 이상 안 보이면 판정 대기 |

그 밖의 등록 기본값은 `src/geometry/mother_registration.py`의 `DEFAULTS`에 있다. 같은 이름을 `registration` 블록에 넣으면 덮어쓴다.

## 코드에서 사용 (웹 UI 등 연동)

```python
from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.process.recipe import load_recipe
from src.vision.detection_adapter import from_ultralytics

config = load_config("config/mvp.json")
service = InspectionService(config, load_recipe("config/recipes/recipe_1.json"))

# 매 프레임: 원본 이미지도 같이 넘겨야 Mother 구멍을 실측한다
frame = from_ultralytics(result, frame_id, capture_timestamp_ms)
snapshot = service.update(frame, image)
# snapshot.phase / status / candidate.issues / registration / occluded / events

service.reset(load_recipe("config/recipes/recipe_2.json"))  # 새 제품 / 레시피 변경
service.reregister()                                         # Mother 재등록
```

작업자용 문구: `from src.app.messages import message, severity` → `message(issue)`.

## 한계와 다음 작업

- 검증 범위: 빈 Mother 사진, 레시피 완성 사진 3장(3×3 조합 모두 정답), 합성 데이터, 웹캠 테스트. 실제 조립 영상으로 가림 시간과 Part ROI를 추가 보정해야 한다.
- 세로 배치는 H1 방향이 모호해 등록을 거부한다.
- 조립 단계에서 Mother로 오검출된 다른 부품은 판정 대상에서 빠진다.
- `web/main.py` 웹 UI는 아직 이 흐름과 연결되지 않았다.

상세: [docs/mother_registration.md](docs/mother_registration.md) · 기존 인수인계: [docs/state_machine_handoff.md](docs/state_machine_handoff.md)
