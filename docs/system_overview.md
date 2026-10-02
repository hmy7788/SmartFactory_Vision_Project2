# System Overview
## Vision-Based Poka-Yoke Assembly Verification System

- **Document Type**: System Overview
- **Status**: Draft / Baseline
- **Domain**: Smart Factory / Machine Vision / Assembly Assistance
- **Primary Objective**: 조립 공정 중 잘못된 부품, 잘못된 위치, 잘못된 조립 상태를 실시간으로 감지하여 작업자가 즉시 수정할 수 있도록 지원하는 Vision 기반 Poka-Yoke 시스템

---

# 1. 프로젝트 한 줄 정의

> **제품별 Recipe와 실시간 머신비전을 결합하여, 조립 과정 중 Mother Part의 각 Hole에 올바른 Bolt와 Part가 조립되었는지를 판단하고 오류 발생 시 즉시 피드백하는 Smart Factory Vision Poka-Yoke 시스템**

---

# 2. 프로젝트 배경

다품종 조립 공정에서는 제품 Variant에 따라 필요한 부품 조합과 조립 위치가 달라질 수 있다.

이 과정에서 다음과 같은 작업 오류가 발생할 수 있다.

- 잘못된 Bolt 사용
- 올바른 Bolt를 잘못된 Hole에 조립
- 잘못된 Part 사용
- Part 누락
- Part의 잘못된 위치 또는 방향 조립
- 조립 순서 오류
- 조립 완료 이후에야 불량을 발견하는 문제

본 프로젝트는 최종 검사만 수행하는 방식이 아니라, **조립 진행 중 현재 상태를 실시간으로 Recipe와 비교하여 오류가 발생한 시점에 바로 알려주는 것**을 목표로 한다.

---

# 3. Poka-Yoke 관점의 핵심 목표

```text
작업 진행
   ↓
실시간 Vision 인식
   ↓
현재 조립 상태 추정
   ↓
Recipe Expected State와 비교
   ↓
정상 → 다음 작업 진행
오류 → 즉시 경고 및 수정 유도
```

즉, 불량이 완성된 뒤 검출하는 것이 아니라 **불량이 만들어지는 과정에서 오류를 조기에 감지**한다.

---

# 4. 조립 대상 구성

## 4.1 Mother Part

Mother Part는 5개의 Hole을 가진 기본 조립 대상이다.

```text
Mother Part
Hole_1
Hole_2
Hole_3
Hole_4
Hole_5
```

Mother Part는 작업 중 위치와 회전이 변할 수 있다.

따라서 Hole ROI를 이미지 절대 좌표로 고정하지 않고, **Mother Part의 실시간 OBB(Oriented Bounding Box)를 기준으로 Local Coordinate System을 생성한 뒤 Hole 위치를 동적으로 계산**한다.

## 4.2 Bolt

```text
bolt_1
- 노란색
- 짧은 Bolt

bolt_2
- 주황색
- 긴 Bolt
```

각 Bolt는 Mother Part의 특정 Hole에 조립된다.

## 4.3 Part

```text
part_2hole
- Hole이 2개인 Part

part_3hole
- Hole이 3개인 Part
```

중요한 기구적 규칙:

> **Part는 항상 자신의 첫 번째 Hole이 Bolt를 통해 Mother Part의 특정 Hole에 결합된다.**

따라서 Mother Part의 특정 Hole은 Part의 Anchor 역할을 한다.

---

# 5. Recipe

프로젝트에서는 총 3개의 Recipe를 사용한다.

각 Recipe는 다음 정보를 포함한다.

```text
Recipe ID
각 조립 Step:
- Mother Hole 번호
- 기대 Bolt 종류
- 기대 Part 종류
- Part 존재 여부
- 조립 순서
```

예시:

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

실제 Recipe 3종의 상세 조합은 팀 확정값에 따라 Config/DB에서 관리한다.

---

# 6. 핵심 Vision 전략

본 프로젝트는 **Unified YOLO OBB 모델 하나**를 사용한다.

초기 Class 구성:

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

AI 모델이 직접 "조립 정상/불량"을 결정하지 않는다.

AI 모델의 역할:

```text
무엇이 있는가?
어디에 있는가?
어떤 방향인가?
```

Process Logic의 역할:

```text
현재 Recipe에서
이 부품이
이 위치와 방향에
있어도 되는가?
```

---

# 7. Mother Part Local Coordinate System

Mother Part가 작업 중 이동 또는 회전할 수 있기 때문에 매 Frame 다음 정보를 갱신한다.

```text
center = (cx, cy)
width
height
angle = theta
```

Mother Part의 장축 방향을 `u`, 그에 수직인 방향을 `v`라고 정의한다.

```text
              +v
               ↑

H1  H2  H3  H4  H5  → +u
```

Mother Part가 회전하면 `u`, `v`도 함께 회전한다.

Hole 위치는 Mother Local Coordinate에서 미리 정의한 비율을 이용하여 계산한다.

```text
H1 = C + alpha_1 * u
H2 = C + alpha_2 * u
H3 = C + alpha_3 * u
H4 = C + alpha_4 * u
H5 = C + alpha_5 * u
```

이를 통해 Mother Part가 0~360° 회전해도 Hole ROI가 함께 갱신되는 구조를 목표로 한다.

---

# 8. Bolt 판정

각 Hole에는 작은 Bolt ROI를 생성한다.

```text
Hole_i
  ↓
Bolt ROI_i
```

Bolt Detection 결과의 중심점 또는 OBB 중심점이 어느 Hole ROI에 포함되는지를 확인한다.

예:

```text
Expected:
Hole_2 = bolt_2

Detected:
bolt_2 center ∈ BoltROI_2
```

→ Bolt PASS

오류 예:

```text
Expected: bolt_1
Detected: bolt_2
```

→ `WRONG_BOLT`

또는

```text
Expected Hole: 2
Detected Hole: 3
```

→ `WRONG_POSITION`

---

# 9. Part 판정

Part는 항상 자신의 첫 번째 Hole이 Bolt를 통해 Mother Part의 특정 Hole에 고정된다.

따라서 해당 Mother Hole을 **Part Anchor**로 사용한다.

```text
Mother Hole_2
   ↓
Bolt Anchor
   ↓
Mother Local +v 방향
   ↓
Part ROI 생성
```

Part ROI는 이미지 화면의 단순 "위쪽"이 아니라 **Mother Local Coordinate의 +v 방향**으로 생성한다.

따라서 Mother Part가 회전해도 Part ROI 역시 함께 회전한다.

```text
              +v
               ↑

          ┌───────────┐
          │ Part ROI  │
          │           │
          └─────┬─────┘
                │
             Bolt ROI
────────────────H_i──────────────── → +u
```

Part 판정 시에는 다음 정보를 사용한다.

- Part Class
- Part OBB/BBox와 Part ROI의 overlap
- 필요 시 Part orientation

예:

```text
Expected:
Hole_2 Anchor
bolt_2
part_3hole

Detected:
bolt_2 @ Hole_2
part_3hole overlaps PartROI_2

→ PASS
```

---

# 10. 실시간 판단

Vision 결과 한 Frame만으로 상태를 변경하지 않는다.

작업자의 손, Motion Blur, 순간적인 Miss Detection 때문에 Detection 결과가 흔들릴 수 있기 때문이다.

따라서 다음과 같은 Temporal Stabilization을 사용한다.

```text
동일 상태가 약 300~500 ms 유지
→ Confirmed State
```

본 프로젝트는 FPS 변화에 덜 민감한 **시간 기반 안정화**를 우선 권장한다.

---

# 11. 전체 시스템 흐름

```text
Recipe 선택
    ↓
Recipe Load
    ↓
Camera Stream
    ↓
Unified YOLO OBB
    ↓
Mother Part Pose
    ↓
Mother Local Coordinate Update
    ↓
Hole Anchor H1~H5 Update
    ↓
Bolt ROI / Part ROI Dynamic Update
    ↓
Bolt / Part Association
    ↓
Current Assembly State
    ↓
Recipe Expected State Compare
    ↓
Temporal Stabilization
    ↓
PASS / NG
    ↓
UI + LED/Buzzer + Event Log
```

---

# 12. 주요 NG 유형

```text
WRONG_BOLT
WRONG_POSITION
WRONG_PART
MISSING_BOLT
MISSING_PART
PART_ORIENTATION_ERROR
SEQUENCE_ERROR
```

---

# 13. 데이터 수집 환경

산업용 머신비전 카메라는 사용하지 않지만, 산업용 Vision의 핵심 설계 원칙인 **반복 가능한 영상 획득 환경**을 저비용 환경에서 모사한다.

```text
Fixed USB Webcam
Fixed Camera Pose
Fixed Working Distance
Fixed Resolution
Controlled Lighting
동일 카메라로 데이터 수집 및 실제 Test
```

학습과 Test는 동일하거나 최대한 유사한 조건에서 수행한다.

---

# 14. 프로젝트의 핵심 기술 포인트

```text
Unified OBB Detection
+
Dynamic Local Coordinate
+
Rotation-Invariant Hole ROI
+
Bolt/Part Spatial Association
+
Recipe Logic
+
Temporal State Machine
```

을 결합하여 실시간 조립 검증 시스템을 구현하는 것이 핵심이다.

---

# 15. 기대 결과

최종 데모에서 다음 동작을 목표로 한다.

```text
1. Recipe 선택
2. Mother Part의 자유로운 위치/회전 상태 인식
3. Hole 좌표 실시간 갱신
4. Bolt 종류와 조립 Hole 판정
5. Anchor 기반 Part 종류와 위치 판정
6. Recipe와 실시간 비교
7. 정상 조립 시 PASS
8. 잘못된 조립 시 즉시 NG 피드백
9. 조립 결과 및 오류 이력 저장
```

---

# 16. 핵심 메시지

> **AI 모델은 부품을 인식하고, Geometry와 Recipe Logic이 조립의 의미를 판단한다.**

이를 통해 일반적인 Image Classification 프로젝트를 넘어, 실제 제조공정의 Poka-Yoke 개념을 모사한 실시간 Vision Assembly Verification System을 구현한다.
