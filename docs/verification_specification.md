# Verification Specification
## Vision-Based Poka-Yoke Assembly Verification System

- **Document Type**: Verification & Validation Specification
- **Status**: Draft
- **Purpose**: Vision, Geometry, Assembly Logic, Real-time Performance를 정량적으로 검증하기 위한 기준 정의

---

# 1. Verification Philosophy

본 프로젝트의 목표는 단순히 데모가 동작하는 것이 아니다.

> **개발 전에 성공 기준을 정의하고, 구현 이후 동일한 기준으로 시스템을 정량 평가한다.**

검증은 다음 5단계로 구분한다.

```text
1. Detection Model Verification
2. Mother Pose / Geometry Verification
3. Bolt / Part Association Verification
4. End-to-End Assembly Verification
5. Robustness / Real-time Verification
```

---

# 2. Test Environment Control

기본 성능 검증은 학습 환경과 동일 또는 유사한 조건에서 수행한다.

고정 조건:

```text
Camera model
Camera height
Working distance
Resolution
Lighting
Background
```

별도 Robustness Test에서만 조건을 변경한다.

---

# 3. Dataset Independence

최종 Test Dataset은 Train/Validation과 분리한다.

금지:

```text
동일 영상의 인접 Frame을 Train과 Test에 나눠 사용
```

권장:

```text
Session A → Train
Session B → Validation
Session C → Test
```

---

# 4. Detection Model Verification

대상 Class:

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

## Metrics

- Precision
- Recall
- mAP50
- mAP50-95
- Class별 Confusion
- OBB angle error for mother_part

## Initial Acceptance Target

| Metric | Target |
|---|---:|
| mAP50 | ≥ 0.90 |
| Mean Precision | ≥ 0.90 |
| Mean Recall | ≥ 0.90 |
| bolt_1 Recall | ≥ 0.95 |
| bolt_2 Recall | ≥ 0.95 |
| part_2hole Recall | ≥ 0.90 |
| part_3hole Recall | ≥ 0.90 |

위 수치는 초기 목표이며 Baseline 이후 팀 합의로 Revision 가능하다.

Revision 시 변경 사유 기록 필수.

---

# 5. Mother Pose Verification

Mother Part가 자유롭게 회전했을 때 OBB 기반 Local Coordinate가 안정적으로 생성되는지 검증한다.

## Test Angles

```text
0°
30°
60°
90°
120°
150°
180°
210°
240°
270°
300°
330°
```

각 Angle:

```text
≥ 10 samples
```

총:

```text
≥ 120 samples
```

---

# 6. Mother Center Error

Ground Truth Mother center와 추정 center 비교.

Metric:

```text
Center Error [pixel]
```

또는 Mother width로 Normalize:

```text
Normalized Center Error
= center_error / mother_width
```

Initial Target:

```text
Median normalized error ≤ 0.02
95th percentile ≤ 0.05
```

---

# 7. Mother Angle Error

Metric:

```text
Angular Error [degree]
```

단 180° symmetry 문제가 해결된 orientation representation 기준으로 측정한다.

Initial Target:

```text
Median angle error ≤ 3°
95th percentile ≤ 7°
```

---

# 8. Hole Anchor Accuracy

각 Mother Pose에서 계산된 H1~H5 좌표와 수동 Ground Truth Hole center를 비교한다.

Metric:

```text
Hole Position Error [pixel]
Normalized Hole Error
= error / mother_width
```

각 Hole별 결과를 보고한다.

Initial Target:

```text
Mean normalized hole error ≤ 0.03
95th percentile ≤ 0.06
```

중요:

실제 Bolt ROI radius/size보다 Hole Error가 충분히 작아야 한다.

---

# 9. Bolt Association Verification

## Scenarios

각 Hole H1~H5에:

```text
bolt_1
bolt_2
empty
```

를 배치하여 평가한다.

Mother rotation을 포함한다.

## Metrics

```text
Bolt Class Accuracy
Bolt-to-Hole Association Accuracy
Wrong Bolt Detection Rate
Wrong Position Detection Rate
Missing Bolt Detection Rate
```

## Recommended Trials

```text
Hole 5개
× Bolt 상태 3개
× 대표 Rotation 6개 이상
```

최소 90 Condition 권장.

---

# 10. Bolt Acceptance Criteria

| Metric | Target |
|---|---:|
| Bolt-to-Hole Association Accuracy | ≥ 95% |
| Wrong Bolt Detection Rate | ≥ 95% |
| Wrong Position Detection Rate | ≥ 95% |
| Missing Bolt Detection Rate | ≥ 95% |

---

# 11. Part ROI Verification

Part는 Anchor Hole 기준으로 Mother Local +v 방향에 생성되는 Part ROI와 association한다.

## Test Conditions

```text
part_2hole
part_3hole
no part
wrong part
correct anchor
wrong anchor
multiple mother rotations
```

---

# 12. Part Spatial Match Metric

추천:

```text
Part ROI overlap ratio
= intersection(part OBB, dynamic Part ROI)
  / area(part OBB)
```

Threshold는 Validation Set에서 선정한다.

Threshold 선정 후 Test Set에서 고정한다.

---

# 13. Part Verification Metrics

```text
Part Type Accuracy
Correct Anchor Detection Rate
Wrong Part Detection Rate
Missing Part Detection Rate
Wrong Position Detection Rate
```

Optional:

```text
Part Orientation Error
```

---

# 14. Part Acceptance Criteria

| Metric | Target |
|---|---:|
| Part Type Accuracy | ≥ 95% |
| Correct Anchor Detection | ≥ 95% |
| Wrong Part Detection | ≥ 95% |
| Missing Part Detection | ≥ 95% |

Part Orientation을 구현할 경우:

```text
Orientation PASS accuracy ≥ 90%
```

를 초기 목표로 한다.

---

# 15. Recipe Verification

총 3개 Recipe 각각에 대해 정상 및 오류 Scenario를 구성한다.

각 Recipe:

```text
Normal Assembly
Wrong Bolt
Wrong Hole
Wrong Part
Missing Bolt
Missing Part
```

가능한 경우:

```text
Sequence Error
```

도 포함한다.

---

# 16. End-to-End Trial Matrix

권장 최소:

| Scenario | Recipe A | Recipe B | Recipe C |
|---|---:|---:|---:|
| Normal | 20 | 20 | 20 |
| Wrong Bolt | 10 | 10 | 10 |
| Wrong Position | 10 | 10 | 10 |
| Wrong Part | 10 | 10 | 10 |
| Missing Bolt | 10 | 10 | 10 |
| Missing Part | 10 | 10 | 10 |

총:

```text
210 trials
```

프로젝트 일정에 따라 최소 120~150회까지 조정 가능하나, 각 오류 유형은 충분한 반복 횟수를 가져야 한다.

---

# 17. End-to-End Metrics

```text
Normal Assembly Acceptance Rate
NG Detection Rate by Error Type
False Alarm Rate
False Negative Rate
Product Completion Success Rate
```

Initial Target:

| Metric | Target |
|---|---:|
| Normal Acceptance | ≥ 95% |
| Wrong Bolt Detection | ≥ 95% |
| Wrong Position Detection | ≥ 95% |
| Wrong Part Detection | ≥ 95% |
| Missing Component Detection | ≥ 95% |
| False Alarm Rate | ≤ 5% |

---

# 18. Temporal Stabilization Verification

목적:

Single-frame false detection이 State Change를 유발하지 않는지 검증.

## Test

다음과 같은 transient noise를 의도적으로 발생:

```text
1~2 Frame object miss
손에 의한 순간 가림
빠른 움직임
Detection confidence drop
```

Expected:

```text
300~500 ms 미만 transient는
최종 PASS/NG 상태를 불필요하게 변경하지 않음
```

---

# 19. End-to-End Latency

Timestamp:

```text
t0 = Stable visual condition이 실제로 형성된 시점
t1 = Inspection result confirmed
t2 = UI / LED / Buzzer feedback 발생
```

Metrics:

```text
Decision Latency = t1 - t0
Feedback Latency = t2 - t0
```

Initial Target:

```text
Median Feedback Latency ≤ 1.0 sec
95th percentile ≤ 1.5 sec
```

Temporal stabilization 시간이 포함된 최종 사용자 체감 Latency를 측정한다.

---

# 20. FPS / Processing Performance

측정:

```text
Average FPS
Median Inference Time
95th Percentile Frame Processing Time
CPU/GPU Utilization (optional)
```

Initial Target:

```text
Average processing FPS ≥ 10
```

본 프로젝트는 고속 컨베이어가 아니라 수작업 조립 Cell을 모사하므로 30 FPS full inference는 필수 조건이 아니다.

---

# 21. Rotation Robustness Test

핵심 시험.

Mother Part를 0~360° 다양한 각도로 회전하면서 동일 Recipe를 수행한다.

평가:

```text
Hole Anchor Accuracy vs Rotation
Bolt Association Accuracy vs Rotation
Part Association Accuracy vs Rotation
End-to-End PASS/NG Accuracy vs Rotation
```

그래프 권장:

```text
X-axis: Mother Rotation Angle
Y-axis: Accuracy / Position Error
```

목표:

특정 Angle 구간에서 성능이 급락하지 않아야 한다.

---

# 22. Translation Robustness Test

Mother Part를 Camera frame 내 여러 위치로 이동.

예:

```text
Center
Top-left
Top-right
Bottom-left
Bottom-right
```

동일 조립 상태에서 결과 비교.

Goal:

Dynamic Local Coordinate가 절대 Image Position에 의존하지 않는지 확인.

---

# 23. Scale Robustness

기본 Test는 동일 Working Distance에서 수행하지만, 제한적인 Scale 변화에 대한 Robustness도 측정 가능.

예:

```text
Nominal
-5%
+5%
```

이는 확장 Test이며 필수 Acceptance에서 제외 가능.

---

# 24. Occlusion Test

작업자의 손이 일시적으로 Mother/Bolt/Part를 가리는 상황.

조건 예:

```text
Light Occlusion
Medium Occlusion
Heavy Occlusion
```

주요 분석:

```text
Recovery Time
False Error Count
Detection Recall
```

MVP에서는 강한 Occlusion을 합격/불합격 조건으로 두기보다 시스템 한계를 설명하는 분석 시험으로 활용한다.

---

# 25. Failure Analysis Taxonomy

모든 실패 Trial은 다음 중 하나로 분류한다.

```text
Mother Detection Failure
Mother Angle Error
Hole Anchor Estimation Error
Bolt False Negative
Bolt Class Confusion
Part False Negative
Part Class Confusion
ROI Association Error
Temporal Logic Error
Recipe Logic Error
State Machine Error
Camera Issue
Operator Procedure Error
Unknown
```

---

# 26. Logging Verification

각 판정 Event에 최소 다음 항목 저장.

```text
timestamp
recipe_id
step_id
mother_pose
expected_hole
expected_bolt
expected_part
detected_bolt
detected_part
result
confidence
latency
```

Acceptance:

```text
30 Product Runs 기준
Critical Event Missing Log = 0
```

---

# 27. Hardware Failure Test

## Camera Disconnect

Expected:

```text
CAMERA_DISCONNECTED
Inspection Stop
UI Error
Application uncontrolled crash 없음
```

## Arduino Disconnect

Expected:

```text
ARDUINO_DISCONNECTED
Vision/Logging은 계속 가능
Hardware feedback unavailable 표시
```

---

# 28. Final Acceptance Summary

초기 프로젝트 성공 기준:

| Category | Target |
|---|---:|
| OBB mAP50 | ≥ 0.90 |
| Bolt-to-Hole Association | ≥ 95% |
| Part Anchor Association | ≥ 95% |
| Wrong Bolt Detection | ≥ 95% |
| Wrong Position Detection | ≥ 95% |
| Wrong Part Detection | ≥ 95% |
| Missing Component Detection | ≥ 95% |
| Normal Assembly Acceptance | ≥ 95% |
| False Alarm Rate | ≤ 5% |
| Median Feedback Latency | ≤ 1.0 sec |
| Average Processing FPS | ≥ 10 |
| Unexpected Crash during final test | 0 |

---

# 29. Reporting

최종 발표/보고서에 최소 포함:

- mAP50 / Precision / Recall
- Mother Angle Error
- Hole Anchor Position Error
- Bolt-to-Hole Association Accuracy
- Part Association Accuracy
- NG 유형별 Detection Rate
- False Alarm Rate
- Rotation Angle별 성능
- Feedback Latency Distribution
- FPS
- Failure Case 분석 이미지

---

# 30. Verification Principle

> **성공 기준을 먼저 정의하고, 시스템을 그 기준에 맞춰 설계하고, 마지막에 같은 기준으로 평가한다.**

목표를 달성하지 못한 경우 Acceptance Criteria를 사후에 임의로 낮추기보다, 실패 원인을 분석하여 시스템 한계와 개선 방향을 명확히 기록한다.
