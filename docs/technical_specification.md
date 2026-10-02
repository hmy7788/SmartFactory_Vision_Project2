# Technical Specification
## Vision-Based Poka-Yoke Assembly Verification System

- **Document Type**: Technical Specification
- **Status**: Draft / Implementation Baseline
- **Scope**: 시스템 구현에 필요한 요구사항, 데이터 구조, Vision Pipeline, Geometry, 상태 관리, 인터페이스 및 권장 소프트웨어 구조
- **Verification**: 정량 검증 기준은 `verification_specification.md`에서 별도 정의

---

# 1. Purpose

본 문서는 프로젝트 구현에 필요한 기술적 요구사항과 설계 기준을 정의한다.

핵심 구현 목표는 다음과 같다.

1. Unified YOLO OBB 모델 한 개로 Mother Part, Bolt, Part를 검출
2. Mother Part OBB를 기준으로 Local Coordinate를 매 Frame 갱신
3. Mother Part의 위치 및 0~360° 회전에 대응하여 Hole 좌표를 실시간 추정
4. 각 Hole에 Bolt ROI 생성
5. 각 Hole을 Anchor로 Mother Local +v 방향에 Part ROI 생성
6. Bolt / Part Detection 결과를 Recipe와 비교
7. Temporal Stabilization 후 실시간 PASS / NG 판단
8. State Machine, UI, Hardware Feedback, Logging과 연동

---

# 2. Project Object Classes

Object Detection/OBB Class는 다음 5개를 기본으로 한다.

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

| Class | Description |
|---|---|
| mother_part | 5개 Hole을 가진 기본 조립 대상 |
| bolt_1 | 노란색 / 짧은 Bolt |
| bolt_2 | 주황색 / 긴 Bolt |
| part_2hole | Hole이 2개인 Part |
| part_3hole | Hole이 3개인 Part |

---

# 3. Functional Requirements

Priority:

- **MUST**: MVP 필수
- **SHOULD**: 구현 권장
- **COULD**: 확장 기능

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | 시스템은 3개의 Recipe 중 하나를 선택할 수 있어야 한다. | MUST |
| FR-002 | Recipe는 외부 JSON/SQLite에서 로드할 수 있어야 한다. | MUST |
| FR-003 | 시스템은 USB Camera 영상을 실시간 입력받아야 한다. | MUST |
| FR-004 | Unified OBB 모델은 mother_part, bolt_1, bolt_2, part_2hole, part_3hole을 검출해야 한다. | MUST |
| FR-005 | Mother Part OBB에서 center, width, height, angle을 추출해야 한다. | MUST |
| FR-006 | Mother Part OBB 기반 Local Coordinate System을 실시간 생성/갱신해야 한다. | MUST |
| FR-007 | Mother Part Local Coordinate에서 H1~H5 Hole Anchor를 계산해야 한다. | MUST |
| FR-008 | 각 Hole Anchor에 Bolt ROI를 생성해야 한다. | MUST |
| FR-009 | 각 Hole Anchor 기준 Mother Local +v 방향으로 Part ROI를 생성할 수 있어야 한다. | MUST |
| FR-010 | bolt detection을 특정 Hole과 association할 수 있어야 한다. | MUST |
| FR-011 | part detection을 특정 Anchor Hole의 Part ROI와 association할 수 있어야 한다. | MUST |
| FR-012 | 현재 조립 상태를 Recipe의 기대 상태와 비교해야 한다. | MUST |
| FR-013 | WRONG_BOLT를 판정해야 한다. | MUST |
| FR-014 | WRONG_POSITION을 판정해야 한다. | MUST |
| FR-015 | WRONG_PART를 판정해야 한다. | MUST |
| FR-016 | MISSING_BOLT / MISSING_PART를 판정할 수 있어야 한다. | MUST |
| FR-017 | 판정은 단일 Frame이 아니라 Temporal Stabilization 후 확정해야 한다. | MUST |
| FR-018 | PASS 시 다음 Step으로 이동해야 한다. | MUST |
| FR-019 | NG 시 현재 Step을 유지하고 오류 상태를 출력해야 한다. | MUST |
| FR-020 | 주요 판정 결과를 DB 또는 Log에 저장해야 한다. | MUST |
| FR-021 | Camera 또는 Model 오류 발생 시 안전하게 Error 상태로 전환해야 한다. | SHOULD |
| FR-022 | Part orientation 검증을 추가할 수 있어야 한다. | SHOULD |
| FR-023 | UI에서 현재 Recipe, Step, Expected, Detected, Result를 표시해야 한다. | SHOULD |
| FR-024 | Arduino LED/Buzzer를 통해 PASS/NG 피드백을 출력할 수 있어야 한다. | SHOULD |

---

# 4. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-001 | Python 3.11+ 기반 모듈형 구조를 사용한다. |
| NFR-002 | AI Detection Layer와 Process Decision Layer를 분리한다. |
| NFR-003 | Recipe, ROI ratio, threshold, model path를 코드에 hard-code하지 않는다. |
| NFR-004 | 시스템은 일반 개발 PC에서 실시간 동작 가능해야 한다. |
| NFR-005 | Camera, Model, Serial 장애가 uncontrolled crash로 이어지지 않아야 한다. |
| NFR-006 | 주요 Event는 timestamp와 함께 기록한다. |
| NFR-007 | Geometry 계산은 frame-rate 수준에서 수행 가능해야 한다. |
| NFR-008 | 새로운 Recipe 추가 시 Vision Model 코드 변경이 없어야 한다. |
| NFR-009 | 단위 테스트 가능한 pure logic을 가능한 많이 분리한다. |

---

# 5. Recommended Technology Stack

## Language

```text
Python 3.11+
```

## Vision / ML

```text
OpenCV
PyTorch
Ultralytics YOLO OBB 계열
```

권장 모델 크기:

```text
nano 또는 small 계열
```

## Database

```text
SQLite
```

## Dashboard

```text
Streamlit
```

## Hardware Communication

```text
pyserial
USB Serial
Arduino Uno/Nano
```

---

# 6. System Architecture

```text
                        ┌─────────────────────┐
                        │     Recipe DB       │
                        └─────────┬───────────┘
                                  │
                                  ▼
┌──────────┐              ┌───────────────┐
│  Camera  │─────────────►│ Vision Engine │
└──────────┘              │ Unified OBB   │
                           └───────┬───────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ Geometry Engine   │
                         │ Mother Local Frame│
                         │ Hole / ROI Update │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ Association Layer │
                         │ Bolt ↔ Hole       │
                         │ Part ↔ Part ROI   │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ Inspection Logic  │
                         │ Recipe Compare    │
                         └─────────┬─────────┘
                                   │
                                   ▼
                         ┌───────────────────┐
                         │ Temporal / State  │
                         │ Machine           │
                         └─────┬─────┬───────┘
                               │     │
                       ┌───────┘     └────────┐
                       ▼                      ▼
                 UI / Dashboard       Arduino / Logger
```

---

# 7. Camera Specification

최소:

```text
USB UVC Camera
1280x720 이상
30 FPS 이상
Color
Fixed Mount
```

권장:

```text
1920x1080 @ 30 FPS
Fixed Focus 또는 AF Disable
Manual Exposure 가능 시 고정
```

환경:

```text
Fixed Camera Pose
Fixed Working Distance
Controlled Lighting
학습과 Test에서 동일 또는 유사한 조건
```

---

# 8. Dataset Specification

## 8.1 Annotation

```text
OBB (Oriented Bounding Box)
```

대상 Class:

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

## 8.2 Data Collection Variation

Mother Part:

```text
0~360° Rotation
Position variation
Scale variation within test range
```

Bolt / Part:

```text
Rotation
Position
Correct assembly
Wrong assembly
Partial occlusion
Multiple objects
Hand appearance
```

## 8.3 Split

연속 Frame을 Random Split하지 않는다.

```text
Session A → Train
Session B → Validation
Session C → Test
```

---

# 9. Unified Detection Output

Vision Layer는 framework-specific 결과를 밖으로 노출하지 않는다.

```python
@dataclass
class OBBDetection:
    class_id: int
    class_name: str
    confidence: float
    center_xy: tuple[float, float]
    width: float
    height: float
    angle_rad: float
    polygon_xy: list[tuple[float, float]]
    timestamp: float
```

---

# 10. Mother Part Local Coordinate

Mother OBB로부터:

```text
C = center
theta = orientation
W = major-axis length
H = minor-axis length
```

장축 unit vector:

```text
u = [cos(theta), sin(theta)]
```

수직 unit vector:

```text
v = [-sin(theta), cos(theta)]
```

단, Hole numbering과 Part +v 방향을 일관되게 유지할 수 있도록 **orientation sign ambiguity를 해결하는 기준**이 필요하다.

중요:

Mother Part 자체가 완전 대칭이라면 180° 방향 ambiguity가 발생할 수 있다.

이 경우 다음 중 하나를 선택해야 한다.

1. 비대칭 시각 특징 활용
2. Reference Marker 추가
3. Recipe/초기 Pose 기준 orientation 유지
4. 별도 orientation classification

프로젝트 구현 전 반드시 하나를 확정한다.

---

# 11. Hole Anchor Definition

Hole 5개의 Local Position을 normalized ratio로 정의한다.

예:

```yaml
mother_geometry:
  hole_alphas:
    h1: -0.40
    h2: -0.20
    h3:  0.00
    h4:  0.20
    h5:  0.40
```

실제 값은 Calibration Dataset에서 측정하여 확정한다.

Hole i:

```text
H_i = C + alpha_i * W * u + beta_hole * H * v
```

보통 `beta_hole`은 중심선 기준으로 0 근처가 된다.

---

# 12. Bolt ROI

각 Hole Anchor 주변에 Mother Local 좌표 기준 Rectangle ROI를 생성한다.

Config 예:

```yaml
bolt_roi:
  half_width_ratio: 0.07
  half_height_ratio: 0.40
```

실제 비율은 Calibration을 통해 확정한다.

Bolt Association 기본안:

```text
bolt center ∈ Bolt ROI_i
```

보조안:

```text
nearest hole distance < threshold
```

---

# 13. Part ROI

Part는 자신의 첫 번째 Hole이 Bolt를 통해 Mother Hole에 결합된다.

따라서 특정 Mother Hole i를 Anchor로 Part ROI를 생성한다.

Part ROI center:

```text
P_i = H_i + offset(part_type) * v
```

Part 종류별 ROI 크기:

```yaml
part_roi:
  part_2hole:
    length_ratio: TBD
    width_ratio: TBD
    offset_ratio: TBD

  part_3hole:
    length_ratio: TBD
    width_ratio: TBD
    offset_ratio: TBD
```

Part ROI는 Mother Local Coordinate에 따라 회전한다.

---

# 14. Part Association

Part는 center-in-ROI보다 overlap 기반 판단을 권장한다.

추천 Metric:

```text
overlap_ratio
= intersection_area(part_obb, part_roi)
  / area(part_obb)
```

예:

```text
overlap_ratio >= 0.60
→ spatial match
```

Threshold는 Validation 단계에서 조정한다.

추가적으로:

```text
|part_angle - expected_angle| <= angle_threshold
```

를 사용할 수 있다.

---

# 15. Recipe Schema

권장 JSON:

```json
{
  "recipe_id": "MODEL_A",
  "steps": [
    {
      "step_id": 1,
      "mother_hole": 2,
      "bolt": "bolt_2",
      "part": "part_3hole"
    },
    {
      "step_id": 2,
      "mother_hole": 5,
      "bolt": "bolt_1",
      "part": null
    }
  ]
}
```

총 3개의 Recipe를 구성한다.

---

# 16. Current Assembly State

```python
@dataclass
class HoleAssemblyState:
    hole_id: int
    bolt: str | None
    bolt_confidence: float | None
    part: str | None
    part_confidence: float | None
    part_overlap: float | None
```

전체:

```python
current_state: dict[int, HoleAssemblyState]
```

---

# 17. Inspection Logic

## 17.1 Bolt

```text
Expected: Hole_2 = bolt_2
```

정상:

```text
bolt_2 associated with Hole_2
```

오류:

```text
bolt_1 @ Hole_2 → WRONG_BOLT
bolt_2 @ Hole_3 → WRONG_POSITION
no bolt @ Hole_2 → MISSING_BOLT
```

## 17.2 Part

```text
Expected:
Anchor = Hole_2
Part = part_3hole
```

정상:

```text
part_3hole overlaps PartROI_2 sufficiently
```

오류:

```text
part_2hole → WRONG_PART
no part → MISSING_PART
part outside ROI → WRONG_POSITION
optional angle mismatch → PART_ORIENTATION_ERROR
```

---

# 18. Temporal Stabilization

단일 Frame 판정 금지.

권장:

```text
stable_duration_ms = 300~500
```

```text
Candidate State 발생
↓
동일 판정 유지
↓
stable_duration 도달
↓
Confirmed Result
```

---

# 19. State Machine

```text
IDLE
LOAD_RECIPE
WAIT_STEP
VERIFY_STEP
STEP_PASS
STEP_ERROR
PRODUCT_COMPLETE
SYSTEM_ERROR
```

Transition:

```text
IDLE
  ↓
LOAD_RECIPE
  ↓
WAIT_STEP
  ↓
VERIFY_STEP
  ├─ PASS → STEP_PASS → WAIT_STEP(next)
  └─ NG   → STEP_ERROR
                  │
                  └─ Corrected → VERIFY_STEP
  ↓
PRODUCT_COMPLETE
```

---

# 20. Error Codes

| Code | Name |
|---|---|
| E001 | CAMERA_DISCONNECTED |
| E002 | MODEL_LOAD_ERROR |
| E003 | MOTHER_NOT_FOUND |
| E004 | MOTHER_POSE_UNSTABLE |
| E005 | INVALID_RECIPE |
| E101 | WRONG_BOLT |
| E102 | WRONG_POSITION |
| E103 | MISSING_BOLT |
| E201 | WRONG_PART |
| E202 | MISSING_PART |
| E203 | PART_ORIENTATION_ERROR |
| E301 | SEQUENCE_ERROR |
| E401 | DB_ERROR |
| E501 | ARDUINO_DISCONNECTED |

---

# 21. Geometry Smoothing

Mother OBB jitter가 Hole ROI jitter로 증폭되지 않도록 smoothing 적용 권장.

Center / Width / Height:

```text
EMA
```

Angle은 circular quantity이므로 단순 산술 평균을 사용하지 않는다.

권장:

```text
sin(theta), cos(theta)를 EMA
→ atan2로 복원
```

---

# 22. Performance Target

권장 Pipeline:

```text
Camera
↓
YOLO OBB
↓
Geometry Update
↓
Association
↓
Temporal Logic
```

초기 Target:

```text
Average Processing FPS ≥ 10
```

공정 작업은 고속 Conveyor보다 느리기 때문에 FPS보다 End-to-End Feedback Latency를 더 중요하게 본다.

---

# 23. Configuration Files

```text
config/
├── app.yaml
├── camera.yaml
├── model.yaml
├── mother_geometry.yaml
├── roi.yaml
└── recipes/
    ├── recipe_a.json
    ├── recipe_b.json
    └── recipe_c.json
```

---

# 24. Recommended Repository Structure

```text
project/
├── README.md
├── agent.md
│
├── docs/
│   ├── system_overview.md
│   ├── technical_specification.md
│   └── verification_specification.md
│
├── config/
│   ├── app.yaml
│   ├── camera.yaml
│   ├── model.yaml
│   ├── mother_geometry.yaml
│   ├── roi.yaml
│   └── recipes/
│
├── data/
│   ├── raw/
│   ├── annotations/
│   └── splits/
│
├── models/
│
├── src/
│   ├── app/
│   ├── vision/
│   ├── geometry/
│   ├── process/
│   ├── database/
│   ├── hardware/
│   └── ui/
│
├── scripts/
└── tests/
```

---

# 25. Implementation Milestones

## M0 Requirement Freeze
- Recipe 3종 확정
- Hole numbering 확정
- Mother orientation ambiguity 해결 방식 확정
- Camera/setup 확정

## M1 Dataset Ready
- 5 Class OBB annotation
- Train/Val/Test split
- 0~360° Mother rotation 포함

## M2 OBB Baseline
- 5 Class Detection
- Mother angle 안정성 확인
- Bolt / Part detection 성능 확인

## M3 Geometry Engine
- Local Coordinate
- Hole Anchor
- Dynamic Bolt ROI
- Dynamic Part ROI

## M4 Inspection Logic
- Bolt association
- Part association
- Recipe compare
- Temporal stabilization

## M5 Integrated MVP
- Camera → YOLO → Geometry → State Machine → UI/Log

## M6 Quantitative Verification
- `verification_specification.md` 기준

---

# 26. Definition of Done

구현 완료 조건:

- Mother Part 위치/회전 변화에서도 Hole ROI가 실시간 갱신됨
- Bolt 종류 및 Hole 위치 판정 가능
- Part 종류 및 Anchor 기반 위치 판정 가능
- Recipe 3종 처리 가능
- Single Frame jitter에 과도하게 반응하지 않음
- PASS / 주요 NG 실시간 피드백 가능
- Event Log 저장
- 검증 명세에 따라 정량 평가 가능
