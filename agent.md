# agent.md
## Approved MVP override (2026-09-22)

Latest workflow addition: recipe selection/reset enters CHECK_MATERIALS.
Count all confident detections across the entire camera frame, requiring exactly
one Mother plus recipe-derived Bolt/Part quantities. Missing, wrong, or excess
materials prevent advancement. Exact inventory held for material_stable_duration_ms
(default 1000ms) transitions once to ASSEMBLING. Then inventory counting stops;
ROI inspection continues, and occlusion/HOLD never returns to material checking.
Only reset/new recipe restarts preparation. READY means materials ready, not
assembly PASS. Snapshot phase/evaluated_phase distinguish transition frames.

The user explicitly approved a narrower MVP. For current implementation these
rules override the original baseline below: screen-left to screen-right H1-H5;
Mother near-horizontal (configurable ±15° initially); Part ROIs rotate with Mother
and extend local-up (-v, screen-up at zero angle), including anchor offset and orientation checks;
unordered whole-recipe inspection; unused Hole components are NG including H5;
missing required components mean IN_PROGRESS, not final NG; automatic PASS/NG
after 400ms stabilization; continue inspection after PASS. Unknown observations
hold inspection immediately. No physical 360° Hole identity or sequence checking
is claimed. See README.md and config/recipes for the implemented contracts.
Original requirements below remain the broader project baseline.

## AI Agent Project Context

This document is the compact source of truth for AI coding agents working on this repository.

Read this file first, then read:

```text
docs/system_overview.md
docs/technical_specification.md
docs/verification_specification.md
```

Do not silently redefine the project.

---

# 1. Project Name

```text
Vision-Based Poka-Yoke Assembly Verification System
```

---

# 2. Project Goal

Build a real-time machine-vision Poka-Yoke system for a small assembly task.

The system must:

1. detect a movable/rotatable Mother Part,
2. establish a Mother-local coordinate system in real time,
3. estimate 5 Mother Hole anchors,
4. detect two Bolt classes,
5. detect two Part classes,
6. determine which Bolt/Part is assembled at which Mother Hole,
7. compare the current assembly state with one of 3 Recipes,
8. provide PASS/NG feedback during assembly,
9. log results.

The system should detect assembly errors during the process, not only after final assembly.

---

# 3. Physical Components

## Mother Part

- one Mother Part type
- contains 5 holes
- can translate and rotate during work
- should support large rotation, ideally 0~360°

## Bolts

```text
bolt_1
- yellow
- short

bolt_2
- orange
- long
```

## Parts

```text
part_2hole
- 2-hole part

part_3hole
- 3-hole part
```

Important mechanical constraint:

> Every Part is attached to the Mother Part by placing the Part's first hole on a specific Mother Hole and fastening it with a Bolt.

Therefore each Part has an explicit Mother Hole anchor.

---

# 4. Recipes

There are exactly 3 project Recipes.

A Recipe should be external configuration, not Python source code.

Recommended schema:

```json
{
  "recipe_id": "MODEL_A",
  "steps": [
    {
      "step_id": 1,
      "mother_hole": 2,
      "bolt": "bolt_2",
      "part": "part_3hole"
    }
  ]
}
```

The exact three recipes may be updated by the team later.

Do not hard-code Recipe-specific logic.

---

# 5. Model Strategy

Use ONE unified OBB object-detection model.

Preferred stack:

```text
Ultralytics YOLO OBB
PyTorch
OpenCV
```

Classes:

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

Do NOT build separate detection models unless a measured performance problem justifies it.

Do NOT use a final image-classification model as the primary architecture.

The main project direction is real-time object detection + geometry + recipe/state logic.

---

# 6. Critical Architecture Principle

Separate:

```text
Perception
from
Process Meaning
```

The model answers:

```text
What object is visible?
Where is it?
What is its orientation?
```

The process logic answers:

```text
Is this object correct for the current Recipe step?
Is it at the correct Mother Hole?
Is the correct Part anchored there?
```

Never embed Recipe semantics inside the detector.

---

# 7. Mother Local Coordinate

Each frame:

1. detect `mother_part` OBB,
2. extract center, width, height, angle,
3. compute local unit axes:

```text
u = Mother long-axis
v = perpendicular axis
```

4. estimate H1~H5 Hole anchors using normalized local coordinates.

Hole coordinates must NOT use fixed image pixels.

They must move and rotate with the Mother Part.

---

# 8. 180-Degree Orientation Ambiguity

This is a critical issue.

The Mother Part can be visually symmetric.

An OBB angle alone may not distinguish:

```text
Hole 1 → Hole 5 direction
```

from the opposite direction.

Before final implementation, the team must choose one solution:

1. reference marker,
2. reliable asymmetric visual feature,
3. orientation initialization + tracking,
4. additional orientation classifier.

Do not ignore this problem.

Hole numbering must remain physically consistent after 180° rotation.

---

# 9. Hole Geometry

Hole locations are configuration values in Mother local coordinates.

Example:

```yaml
hole_alphas:
  h1: -0.40
  h2: -0.20
  h3:  0.00
  h4:  0.20
  h5:  0.40
```

Actual values must be calibrated from images.

Recommended module:

```text
geometry/hole_estimator.py
```

---

# 10. Bolt Association

For every Hole:

```text
Hole Anchor
→ Dynamic Bolt ROI
```

Preferred first implementation:

```text
bolt center inside Bolt ROI
```

Alternative/fallback:

```text
nearest-hole association
with maximum distance threshold
```

Expected results include:

```text
CORRECT_BOLT
WRONG_BOLT
WRONG_POSITION
MISSING_BOLT
```

---

# 11. Part Association

Part placement is anchor-based.

If the Recipe says:

```text
Hole 2
bolt_2
part_3hole
```

then Hole 2 is the Part anchor.

Generate a Part ROI from Hole 2 in Mother-local `+v` direction.

Important:

The Part ROI must NOT be "image upward".

It must rotate with the Mother local coordinate system.

Different Part types can have different:

```text
ROI length
ROI width
offset from anchor
```

---

# 12. Part Spatial Match

Prefer overlap-based association rather than only checking Part center.

Recommended metric:

```text
intersection(part_obb, part_roi) / area(part_obb)
```

Threshold is configurable and must be selected using Validation data.

Optional orientation check:

```text
part angle vs expected Mother-local direction
```

---

# 13. Temporal Stabilization

Never transition state based on one frame.

Use:

```text
stable_duration_ms ≈ 300~500 ms
```

Default should be configurable.

A short detection miss caused by hand occlusion or blur should not immediately produce a new process state.

---

# 14. State Machine

Recommended states:

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

Normal flow:

```text
LOAD_RECIPE
→ WAIT_STEP
→ VERIFY_STEP
→ STEP_PASS
→ NEXT STEP
```

Error:

```text
VERIFY_STEP
→ STEP_ERROR
→ operator corrects assembly
→ VERIFY_STEP
```

---

# 15. Error Types

Required process errors:

```text
WRONG_BOLT
WRONG_POSITION
MISSING_BOLT
WRONG_PART
MISSING_PART
SEQUENCE_ERROR
```

Optional:

```text
PART_ORIENTATION_ERROR
```

System errors:

```text
CAMERA_DISCONNECTED
MODEL_LOAD_ERROR
MOTHER_NOT_FOUND
MOTHER_POSE_UNSTABLE
INVALID_RECIPE
DB_ERROR
ARDUINO_DISCONNECTED
```

---

# 16. Dataset Rules

OBB annotation required.

Classes:

```text
mother_part
bolt_1
bolt_2
part_2hole
part_3hole
```

Dataset must include:

```text
Mother 0~360° rotation
Mother translation
Correct assembly
Wrong bolt
Wrong hole
Wrong part
Part absent
Bolt absent
Hand occlusion
Multiple visible components
```

Do NOT randomly split adjacent video frames across Train/Test.

Prefer session-based split.

---

# 17. Camera Assumptions

The project uses a fixed USB webcam.

Testing is performed under conditions similar to training:

```text
same camera
same working distance
same lighting
same background
```

The Mother Part itself is allowed to move and rotate.

---

# 18. Coding Architecture

Preferred repository layout:

```text
src/
├── app/
├── vision/
├── geometry/
├── process/
├── database/
├── hardware/
└── ui/
```

Responsibilities:

## vision

- camera input
- YOLO model
- normalize detections

No Recipe logic.

## geometry

- Mother local frame
- Hole estimation
- Bolt ROI
- Part ROI
- spatial association

No UI or database logic.

## process

- Recipe
- current assembly state
- temporal filter
- state machine
- PASS/NG decisions

## hardware

- Arduino LED/Buzzer
- serial connection

## database

- run logs
- event logs

## ui

- display only
- no core inspection logic

---

# 19. Data Types

Use dataclasses/type hints.

Example:

```python
@dataclass
class OBBDetection:
    class_name: str
    confidence: float
    center_xy: tuple[float, float]
    width: float
    height: float
    angle_rad: float
    polygon_xy: list[tuple[float, float]]
    timestamp: float
```

Do not pass raw Ultralytics result objects into process logic.

---

# 20. Configuration

Do not hard-code:

```text
camera index
model path
confidence threshold
hole ratios
ROI sizes
part ROI offsets
overlap threshold
stable duration
serial port
recipe definitions
database path
```

Use YAML/JSON configuration.

---

# 21. Recommended Implementation Order

```text
1. Repository skeleton
2. Config loader
3. Recipe loader
4. Camera capture
5. Unified OBB inference
6. Detection normalization
7. Mother local coordinate
8. Hole anchor estimation
9. Bolt ROI + association
10. Part ROI + association
11. Temporal stabilization
12. State machine
13. DB logging
14. UI
15. Arduino feedback
16. Quantitative verification
```

---

# 22. MVP Scope

Must include:

```text
1 camera
1 unified OBB model
5 object classes
3 recipes
5 Mother holes
Mother rotation/translation handling
Bolt verification
Part verification
real-time PASS/NG
temporal stabilization
logging
```

Do not prematurely add:

```text
multi-camera
3D vision
depth camera
human action recognition
complex tracking
segmentation
multiple AI models
cloud backend
real MES/PLC integration
```

unless a measured requirement justifies it.

---

# 23. Verification Is Part of the Product

Before claiming completion, use:

```text
docs/verification_specification.md
```

Important targets include:

```text
mAP50
Mother angle error
Hole anchor position error
Bolt-to-Hole association accuracy
Part association accuracy
NG detection rate
false alarm rate
latency
FPS
rotation robustness
```

---

# 24. Agent Rules

When editing this project:

1. Read this file first.
2. Read the relevant specification.
3. Preserve the one-model architecture unless evidence demands otherwise.
4. Preserve perception/process separation.
5. Do not silently change Recipe semantics.
6. Do not use fixed image-coordinate Hole ROIs.
7. Do not define Part ROI in screen-up direction; use Mother-local direction.
8. Do not ignore Mother orientation ambiguity.
9. Avoid state transitions from a single frame.
10. Keep changes incremental and testable.
11. Add deterministic unit tests for geometry and process logic.
12. Do not over-engineer beyond student-project scope.

---

# 25. Definition of Done

The project is not done when YOLO draws boxes.

It is done when:

```text
Mother moves/rotates
→ Hole anchors follow correctly
→ Bolt and Part are spatially associated
→ Recipe state is reconstructed
→ real-time PASS/NG is stable
→ errors are logged
→ quantitative tests are completed
```

The main technical value is:

> **OBB perception + rotation-invariant local geometry + Recipe-based real-time Poka-Yoke decision logic.**
