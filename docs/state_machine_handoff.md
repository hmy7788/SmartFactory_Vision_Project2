# State Machine 인수인계

## 소스 책임

| 경로 | 책임 |
|---|---|
| src/contracts | 입력 OBBDetection/DetectionFrame, 결과 Snapshot/Phase/Status |
| src/vision/detection_adapter.py | 모델 결과 정규화, 한글 클래스 매핑 |
| src/geometry | Mother 장축, Hole/ROI, polygon 교차, 부품 연결 |
| src/process/materials.py | Recipe에서 요구 수량 산출, 화면 전체 개수 비교 |
| src/process/evaluator.py | Hole별 Recipe 판정 |
| src/process/temporal.py | 시간 안정화 |
| src/process/state_machine.py | 준비→조립 단방향 전이와 확정 판정 |
| src/app/inspection_service.py | 프레임 처리, 입력 검증, 이벤트 |
| scripts / tests | 샘플 검증·재생 / 결정론적 회귀 테스트 |

기존 src/detection, src/recipe, src/rule_based, src/classification는 별도 팀 코드다. 이 구현의 Recipe는 config/recipes를 사용한다. 루트에서 python -m 명령으로 실행한다.

## 모델/UI 연동 예시

```python
import json
from pathlib import Path
from src.app.config import load_config
from src.process.recipe import load_recipe
from src.app.inspection_service import InspectionService
from src.vision.detection_adapter import from_ultralytics

config = load_config("config/mvp.json")
recipe = load_recipe("config/recipes/recipe_1.json")
mapping = json.loads(Path("config/class_mapping.json").read_text(encoding="utf-8"))
service = InspectionService(config, recipe)  # 루프 밖에서 한 번 생성

def on_result(result, frame_id, capture_timestamp_ms):
    frame = from_ultralytics(result, frame_id, capture_timestamp_ms, mapping)
    return service.update(frame)

# 새 제품 / Recipe 변경:
# service.reset(load_recipe("config/recipes/recipe_2.json"))
```

result는 원본 영상 크기의 obb.xywhr/cls/conf와 names를 제공한다. width축 각도는 radian, 이미지 x는 오른쪽/y는 아래다. resize/letterbox 좌표 복원은 입력 전에 완료한다. timestamp는 캡처 시점의 단조 증가 millisecond, frame_id는 증가 정수다. detection_id는 프레임 내에서만 유일하면 된다.

카메라 오류 시 새 id/timestamp로 DetectionFrame(..., detections=(), input_valid=False)를 전달한다. 코어 호출 자체가 멈추면 자동 장애 검출은 불가능하므로 호출 측 watchdog이 필요하다. 동일 프레임을 새 id로 반복 입력하지 않는다. frame gap 기본 250ms를 초과하면 HOLD하므로 실제 추론속도를 측정하고 필요하면 팀 합의로 설정을 변경한다.

## 출력 해석 (UI 필수)

- phase: 현재 CHECK_MATERIALS/ASSEMBLING.
- evaluated_phase: 이번 프레임을 검사한 단계.
- candidate: 최신 후보/Issue. READY는 재료 준비이며 완성품 PASS가 아니다.
- status/confirmed: 마지막 확정 표시/근거. 짧은 miss에는 이전 PASS가 남을 수 있다.
- stable: 이번 후보의 시간 조건 충족 여부. false이면 안정화 중이라고 표시한다.
- materials.expected/observed: 준비 종류별 수량. 조립 단계에서는 빈 dict.
- geometry/observed: 조립 Hole/ROI/연결 근거. overlay는 개발 옵션으로 사용한다.
- events: 변경 시만 생성. 준비 완료 이벤트는 ASSEMBLY_STARTED.

전환 프레임은 evaluated_phase=CHECK_MATERIALS, phase=ASSEMBLING, candidate=READY, stable=true다. 조립 증거가 초기화되므로 status=HOLD, confirmed=None이다. UI는 전환 이벤트로 '재료 확인 완료, 조립 시작'을 표시하고 다음 프레임부터 조립 판정을 사용한다.

HOLD는 유효 관측 부족으로 즉시 진입할 수 있다. Mother 유실/다중 Mother/각도 제한/연결 모호/입력 오류가 해당한다. 준비 단계의 다중 Mother는 초과 수량 NG다. 조립 중 HOLD/NG여도 준비 단계로 복귀하지 않는다.

event_id는 reset마다 초기화된다. 저장 측에서 run_id와 UTC 시각을 추가한다. PASS 복귀가 여러 번 가능하므로 PASS 이벤트 수를 제품 수로 세지 않는다. 실제 DB/웹 전송은 코어 밖에서 구현한다.

## 설정·재생

confidence_threshold=0.5, material_stable_duration_ms=1000, stable_duration_ms=400. Hole alpha는 장축 W 비율, beta는 단축 H 비율. Bolt half-width는 W, half-height는 H 기준. Part width/length/offset은 모두 W 기준이며 중심=Hole-offset·v, 회전=Mother 각도다. Part 방향 오차는 Mother 수직축 대비 ±20° 초기값. overlap은 교차면적/검출 OBB 면적이며 IoU가 아니다. Anchor는 OBB와 보정 비율의 근사값이다.

```powershell
python -m scripts.replay_detections --demo --recipe recipe_1 --output inspection_results.jsonl
python -m scripts.replay_detections --input detections.jsonl --recipe recipe_1 --output replay_results.jsonl
```

입력 JSONL 한 줄 예:

```json
{"frame_id":0,"timestamp_ms":0,"input_valid":true,"detections":[{"detection_id":"m","class_name":"mother_part","confidence":0.99,"center_xy":[600,700],"width":1000,"height":160,"angle_rad":0}]}
```

출력 snapshot JSONL은 입력 detection JSONL과 다르다. 그대로 재입력할 수 없다. 출력은 새 파일만 생성한다.

## 다음 담당 작업

1. 모델: 3구/5구 혼동, 2구·주황 볼트 미검출, 조립/손 가림 개선. 샘플을 학습에 사용하면 독립 테스트 사진을 새로 확보한다.
2. 기하: 실제 조립 사진으로 Part ROI/Anchor/overlap 보정. 빈 Mother ROI 시각화만 확인된 상태다.
3. 카메라/UI: 위 API에 연속 캡처 결과 연결, phase/수량/원인/stable 표시, 새 작업/reset 제공.
4. 통합: 준비 자동전환, NG 수정, 가림/단절/지연을 실제 영상으로 측정.

검출 객체 개수는 실제 재료 개수와 다를 수 있다. 미검출·동일 객체의 교차 클래스 중복·손에 든 부품이 조립 위치와 겹침 등의 한계를 갖는다. 검출 클래스나 수량을 Recipe에 맞게 임의 보정하지 않는다.
