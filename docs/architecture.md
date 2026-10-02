# 아키텍처 개요

비전 기반 작업자 오조립 방지(Poka-Yoke) 시스템의 전체 구조. 카메라(또는 영상) → 검출 모델 →
판정 코어 → UI(웹 또는 CLI) 순서로 동작하며, **판정 코어는 검출 모델·UI와 완전히 분리**되어 있다.

## 1. 전체 데이터 흐름

```
카메라/영상 파일
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│ 검출 (Detection) — --model-type으로 교체 가능              │
│   rtdetr / yolo (AABB)  →  src/vision/rtdetr_adapter.py   │
│   yolo-obb (OBB)        →  src/vision/detection_adapter.py│
│   rule_based (모델 없음) →  src/vision/rule_based_adapter.py│
└─────────────────────────────────────────────────────────┘
     │  DetectionFrame(frame_id, timestamp_ms, [OBBDetection, ...])
     │  ── src/contracts/detections.py: 검출 계층과 판정 코어 사이의 유일한 계약
     ▼
┌─────────────────────────────────────────────────────────┐
│ 판정 코어 (Core) — src/app/inspection_service.py           │
│   기하: src/geometry/{mother_frame,roi_builder,association,spatial}.py │
│   판정: src/process/{evaluator,materials,state_machine,temporal}.py    │
│   레시피: src/process/recipe.py + config/recipes/*.json                │
└─────────────────────────────────────────────────────────┘
     │  Snapshot(phase, status, candidate, confirmed, stable, geometry, observed, events, ...)
     │  ── src/contracts/inspection.py: 코어와 UI 사이의 유일한 계약
     ▼
┌─────────────────────────────────────────────────────────┐
│ UI — 둘 다 같은 Snapshot을 그린다, 코어는 안 건드림           │
│   CLI:  scripts/live_inspection.py + src/app/hud.py (OpenCV 창)   │
│   웹:   web/server.py + pipeline.py + static/app.js (브라우저)     │
└─────────────────────────────────────────────────────────┘
```

**핵심 설계 원칙**: 위 3개 계층은 각자 독립적으로 교체 가능하다. 검출 모델을 바꿔도(`--model-type`)
판정 로직은 그대로고, UI를 바꿔도(CLI↔웹) 판정 로직은 그대로다. 이게 가능한 이유는 계층 사이를
`DetectionFrame`/`Snapshot`이라는 고정된 데이터 계약(`src/contracts/`)으로만 주고받기 때문 — 검출도
UI도 서로의 내부 구현을 모른다.

## 2. 검출 계층 — `src/vision/`

| 파일 | 역할 |
|---|---|
| `rtdetr_adapter.py` | `RTDETRAdapter`. RT-DETR/YOLO(detect, AABB) 결과 → `DetectionFrame`. AABB는 회전각이 없어서, mother는 구멍 위치 직선 피팅(`src/rule_based/hole_count_check.py`의 `find_bar_and_holes`/`estimate_mother_angle` 재사용)으로, 부품은 `cv2.minAreaRect`로 각도를 영상에서 복원한다. 프레임 간 각도 평활화(지수이동평균) 상태를 인스턴스에 들고 있음 |
| `detection_adapter.py` | `from_ultralytics`. YOLO-OBB 결과 → `DetectionFrame`. OBB는 결과에 각도가 이미 있어 그대로 변환만 함 (CLAUDE.md가 확정한 메인 파이프라인) |
| `rule_based_adapter.py` | `RuleBasedAdapter`. 학습된 모델 없이 classical CV(Otsu 이진화 + 색상 HSV + 구멍 개수)로 직접 검출. 한계는 `docs/rule-based-live-limitations.md` 참고 |

세 어댑터 모두 같은 출력 계약(`DetectionFrame`)을 만들기 때문에, 호출부(`scripts/live_inspection.py`,
`web/source.py`)는 `--model-type` 값만 보고 어댑터를 고르면 된다.

## 3. 데이터 계약 — `src/contracts/`

- `detections.py`: `OBBDetection`(detection_id, class_name, confidence, center_xy, width, height,
  angle_rad — 이미지 +x에서 +y(아래) 방향 라디안), `DetectionFrame`(frame_id, timestamp_ms,
  detections 튜플, input_valid). `CLASSES` = 5개 고정 클래스(`bolt_1, bolt_2, mother_part,
  part_2hole, part_3hole`).
- `inspection.py`: `Status`(READY/IN_PROGRESS/PASS/NG/HOLD), `Phase`(CHECK_MATERIALS/ASSEMBLING),
  `Issue`(code, hole_id, expected, observed), `Candidate`(status, issues), `Snapshot`(그 프레임의
  전체 결과 — UI가 그리는 건 이것뿐).

## 4. 기하 계층 — `src/geometry/`

카메라 좌표계의 mother 박스 하나로부터, 레시피가 참조하는 H1~H5 구멍의 화면 좌표와 ROI(관심영역)를
계산한다.

| 파일 | 역할 |
|---|---|
| `mother_frame.py` | `major_axis()`: OBB의 각도를 방향-무관(mod π)으로 정규화 (심 대칭 막대라 어느 쪽이 "+"인지 검출기가 모름). `mother_pose()`: 중심/길이/두께/각도 + 로컬 축 `u`(장축)/`v`(장축의 -90°, mother-local 위쪽) 계산, `max_mother_angle_deg` 초과 시 `ValueError` |
| `roi_builder.py` | `build_geometry()`: `hole_alphas`(H1~H5의 장축 위치 비율)로 구멍 좌표, 볼트/파트 ROI 사각형 계산. 파트 ROI는 mother 위쪽(`part_rois`)과 아래쪽(`part_rois_down`) 둘 다 항상 계산 |
| `association.py` | `associate()`: 검출된 볼트/파트를 어느 구멍(H1~H5)에 속하는지 매칭. 파트는 above/below 양쪽 ROI를 항상 평가해서 실제 매칭된 쪽(`side`)을 기록 — "위/아래 어느 쪽인지가 맞는가"는 평가 단계(`evaluator.py`)로 미룸 |
| `spatial.py` | 사각형 생성, 다각형 겹침/포함/교차 등 순수 기하 유틸 |

## 5. 판정 코어 — `src/process/` + `src/app/inspection_service.py`

`InspectionService.update(frame)`가 매 프레임 호출되는 유일한 진입점.

```
CHECK_MATERIALS (재료 확인)
  evaluate_materials(): 레시피가 요구하는 5클래스 개수 vs 전체 프레임의 클래스 개수(위치 무관)
  → READY(정확)가 material_stable_duration_ms 이상 안정되면 ASSEMBLING으로 전환
        │
        ▼
ASSEMBLING (조립 검사)
  build_geometry() → associate() → evaluate()/evaluate_symmetric()
  → 프레임마다 PASS/NG/IN_PROGRESS 후보, stable_duration_ms 이상 안정돼야 "확정(confirmed)"
```

- **`evaluator.py`**: `evaluate(recipe, observed, expected_side)` — 각 구멍의 관측값을 레시피와
  비교해 `Issue` 생성 (`WRONG_BOLT`, `WRONG_PART`, `MISSING_*`, `EXTRA_COMPONENT`,
  `UNEXPECTED_COMPONENT`, `PART_ORIENTATION_ERROR`, `PART_WRONG_SIDE`).
  `evaluate_symmetric()` — mother는 좌우 대칭이라 구멍 번호를 반대쪽 끝에서 읽었을 수도 있다:
  "직접 읽기"(부품은 위쪽이어야 함, `allow_parts_below`로 완화 가능)와 "미러 읽기"(번호를
  6-h로 재배정하고 **반드시 아래쪽**이어야 함 — 진짜 180도 회전이면 번호와 위/아래가 항상 같이
  뒤집히기 때문)를 둘 다 계산해 더 나은 쪽을 채택. 그래서 부품 하나만 반대쪽에 붙은 진짜 오류와,
  조립체 전체가 180도 돈 정상 상태가 정확히 구별된다 (`tests/test_relaxed_orientation.py`).
- **`materials.py`**: `evaluate_materials()` — 위치 무관 전체 개수 비교.
- **`state_machine.py`** + **`temporal.py`**: `TemporalFilter`가 "같은 후보가 N개 프레임 이상,
  duration_ms 이상 연속"이어야 안정(stable)으로 인정 (오검출 깜빡임 방지). `StateMachine`이
  단계 전환(재료→조립)과 `confirmed`(마지막으로 확정된 판정)를 관리. **HOLD는 확정을 비우지만
  기존 confirmed는 UI가 별도로 기억**(웹 UI의 `S.shown`, CLI의 마지막 프레임 유지) — 손이 지나가는
  일시적 HOLD가 화면에 그대로 노출되지 않게 하기 위함.
- **`recipe.py`**: `Recipe`/`Placement` — mother_hole(1~4, H5는 접합부라 금지)마다 필요한 볼트+파트.
  `config/recipes/recipe_{1,2,3}.json`.

## 6. 룰베이스 — `src/rule_based/`

| 파일 | 역할 |
|---|---|
| `hole_count_check.py` | 완성된 조립체 사진에서 구멍 개수+위치로 Model A/B/C 판별 (CLAUDE.md 3-2 필수 항목). `find_all_blobs`/`find_bar_and_holes`는 `rtdetr_adapter.py`·`rule_based_adapter.py`도 재사용하는 공용 컨투어 검출 함수 |
| `rule_based_adapter.py`(§2) | 위 로직을 멀티 오브젝트 실시간 검출로 확장 — 한계는 `docs/rule-based-live-limitations.md` |
| `live_hole_check.py`, `capture_hole_check.py` | 룰베이스 라이브 테스트/촬영 스크립트 (독립 실행, 판정 코어와 무관) |

## 7. 두 UI — 같은 코어, 다른 화면

| | CLI (`scripts/live_inspection.py`) | 웹 (`web/`) |
|---|---|---|
| 실행 | `python -m scripts.live_inspection` | `python -m web.server` |
| 화면 | OpenCV 창 (로컬 1인용) | 브라우저 (여러 명, 원격 가능) |
| 그리기 | `src/app/hud.py` — PIL로 한글 텍스트 + cv2로 도형, 매 프레임 다시 그림 | `web/static/app.js` — WebSocket으로 Snapshot을 JSON으로 받아 DOM 갱신 |
| 이력/분석 | 없음 | `web/store.py`(SQLite) — 이력·타임라인·FPY·파레토·진단 탭 |
| 데모 모드 | 없음 (영상 파일로 대체) | `DemoSource` — 카메라·모델 없이 합성 시나리오 재생 |

- **`web/source.py`**: `Source` 프로토콜(`frames() -> Iterator[(DetectionFrame, JPEG|None)]`)의
  3가지 구현 — `DemoSource`(합성), `JsonlSource`(기록 재생), `CameraSource`(실제 카메라/영상 +
  §2의 검출 어댑터). 카메라 스레드와 추론 스레드를 분리해(threaded 모드) 무거운 모델도 영상이
  끊기지 않게 함.
- **`web/pipeline.py`**: `Source` → `InspectionService.update()` → `Store`에 변화만 기록 → 화면용
  JSON(payload)으로 변환해 콜백. **코어를 직접 건드리지 않는다** (import만 함) — 그래서 코어를
  바꾸면(예: `association.py` 수정) 웹 UI도 자동으로 그 판정을 쓴다.
- **`web/server.py`**: Starlette 기반 REST(`/api/*`) + WebSocket(`/ws`) + MJPEG(`/video`). `--config`
  기본값은 `--source`별로 다름 — `demo`/`jsonl`은 `config/mvp.json`(데모 시나리오가 이 값 기준으로
  짜여 있음), `camera`는 `config/rtdetr_live.json`(각도·좌우뒤집힘 완화).
- **`web/static/app.js`**: `hole_numbering === "mirrored"`일 때 물리적 구멍 번호와 레시피 번호가
  반대(`6-h`)라는 걸 알아야 하는 3곳(관측값 표시, 영상 오버레이 H번호, 진단 ROI 색상)에서 이 보정을
  적용 — CLI의 `hud.py`와 동일한 로직.

## 8. Config — `config/`

| 파일 | 용도 |
|---|---|
| `mvp.json` | 팀 원안. `max_mother_angle_deg: 15`, `allow_parts_below`/`allow_mirrored_holes` 없음(=둘 다 꺼짐, 부품은 위쪽만) |
| `rtdetr_live.json` | 라이브 카메라용 완화 설정. 각도 89.9°, `allow_mirrored_holes: true`(180도 회전 인식), `allow_parts_below: false`(그래도 부품 하나만 아래쪽이면 NG) |
| `recipes/recipe_{1,2,3}.json` | Model A/B/C에 대응하는 `Recipe` |
| `class_mapping.json` | 한글 클래스명 → 영문 5클래스 (yolo-obb 경로 전용, 학습 데이터가 한글 라벨일 때) |

`src/app/config.py`가 로드 시 `hole_alphas`/`part_rois` 등의 유효성을 검증한다.

## 9. 오프라인 도구 (판정 파이프라인과 무관)

런타임 흐름과 별개로, 데이터 준비·모델 학습용 스크립트들이 있다 (실행 시점에 판정 코어를 쓰지 않음):

- `src/detection/`: ICONIC 자동 라벨링, 라벨 데이터 병합, 원본 소스 → 통합 데이터셋(`prepare_obb_from_sources.py`)
- `src/detection/yolo11/`: YOLO11n-OBB 데이터셋 빌드·학습·평가(mAP·긴 변 각도 오차·CPU 속도)·실시간 확인
- `src/detection/rt-detr/`: RT-DETR 전용 학습/평가 스크립트
- `src/classification/`: 완성 조립체 Model A/B/C 분류(ResNet-18 파인튜닝, CLAUDE.md 3-2) — `docs/classification.md`
- `scripts/check_weights.py` + `src/vision/model_loader.py`: 받은 가중치가 YOLO/RT-DETR 중 무엇인지 판별하고 시스템에 맞는지 점검
- `scripts/evaluate_video.py` + `src/app/evaluation_log.py`: 영상 기반 공정 평가(`live_inspection.py --eval-log`) — `docs/video-evaluation.md`
- 학습 결과 가중치는 모두 `weights/`, 학습 로그는 `runs/`, 리포트는 `reports/`
- 실험 기록: `docs/rt-detr-experiment.md`, `docs/detection_obb.md`, `docs/cropped-dataset.md`

## 10. 테스트 — `tests/`

170개 (`python -m pytest tests -q`) + MES JUnit 13개(`mes/test_mes.cmd`).

| 파일 | 대상 |
|---|---|
| `test_mvp.py`, `test_material_workflow.py` | 코어(기하/판정/디바운스/재료→조립 전환) |
| `test_relaxed_orientation.py` | mother 아래쪽=NG + 180도 회전 인식 (§5) |
| `test_rtdetr_adapter.py`, `test_rule_based_adapter.py` | §2의 두 어댑터, 합성 이미지로 모델 없이 검증 |
| `test_web.py`, `test_web_ui.js`(node) | 웹 UI 전체(소스/파이프라인/서버/프론트 파생 상태) |
| `test_store.py`, `test_mes_link.py`, `test_clear_wait.py` | SQLite 이력 저장, MES 연동, 작업 완료 후 대기 |
| `test_obb_dataset.py`, `test_model_loader.py` | YOLO-OBB 데이터셋·평가, 가중치 로더 |
| `test_video_evaluation.py` | 영상 평가 채점 |

## 11. 파일 맵 요약

```
src/
├── contracts/        데이터 계약 (DetectionFrame, Snapshot) — §3
├── vision/            검출 → DetectionFrame 어댑터 — §2
├── geometry/          mother 포즈 → 구멍 좌표 → 매칭 — §4
├── process/           판정/상태머신/레시피 — §5
├── app/               InspectionService(코어 진입점), config, CLI HUD
├── rule_based/         classical CV — §6
├── detection/          (오프라인) 데이터셋/학습 — yolo11/, rt-detr/ — §9
└── classification/     완성체 Model A/B/C 분류 — §9
scripts/
├── live_inspection.py  CLI 라이브 검사 앱
├── run_ui.py            웹 UI 실행기 (가중치/카메라 선택)
├── evaluate_video.py, check_weights.py   영상 공정 평가 채점, 가중치 점검
└── replay_detections.py, verify_materials.py, visualize_rois.py, demo_data.py   개발용 보조 스크립트
web/                    웹 UI(FastAPI/Starlette + 순수 JS) — §7
config/                 판정 설정 + 레시피 — §8
tests/                  §10
docs/                   이 문서 포함 실험/사용법 기록
```
