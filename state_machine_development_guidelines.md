# State Machine 담당 개발 가이드라인

## 구현된 MVP 우선 규칙 (사용자 승인, 2026-09-22)

후속 확정: Recipe 선택/reset 후 CHECK_MATERIALS에서 카메라 전체 재료 수량을 확인한다. Recipe에서 산출한 종류별 수량과 Mother 1개가 정확히 일치할 때만 1초 안정화 후 ASSEMBLING으로 전환한다. 다른 종류/초과 수량/부족은 전환을 차단한다. 이후 개수 검사는 중단하며 ROI 검사만 수행하고, 가림/NG가 발생해도 준비 단계로 복귀하지 않는다. 상세 출력 계약과 설정은 README의 재료 준비 절을 따른다.

아래의 초기 가이드에서 미확정이었던 정책을 사용자가 확정했다. **현재 구현은 이 절과 README.md를 우선 적용**한다. 기존의 자유 회전/Step 전이는 향후 확장 기준으로만 남긴다.

- Hole은 화면 왼쪽부터 H1~H5. Mother 수평 ±15° 기본 제한. 물리적 360° 번호 추적 제외.
- Part ROI도 Mother 회전을 따른다(후속 사용자 확정). 중심 offset과 사각형을 Mother-local 위쪽(-v) 기준으로 회전시키며 Part 방향 검증도 Mother에 상대적으로 수행한다. 수평일 때는 기존 화면 위쪽과 같다. 아래 초기 문서의 화면 위쪽 고정 설명은 이 규칙으로 대체한다.
- 3종 Recipe는 순서 없이 전체 조합 검사. `placements` JSON으로 관리하며 Step 전이/순서 오류 제외.
- 비지정 Hole 및 H5의 추가 조립은 NG. Mother와 무관한 예비 부품은 제외.
- 버튼 없이 실행. 부족하면 IN_PROGRESS, 오류면 NG, 모두 맞으면 PASS, 불명확하면 HOLD.
- 400ms 안정화 후 공정 판정, PASS 뒤에도 재검사. 입력 무효화 HOLD는 즉시 적용.
- 실측 치수/실제 모델은 미제공. 설정 기본값은 UNVALIDATED_DEFAULTS이며 실제 성능 검증을 대체하지 않음.

현재 구현/실행법은 README.md, 설정은 config/mvp.json, 검증은 tests/test_mvp.py를 참고한다.

작성 기준: 2026-09-22. 현재 루트의 `agent.md`, `system_overview.md`, `technical_specification.md`, `verification_specification.md`를 읽고 작성했다. 원문에 적힌 `docs/` 경로와 달리 현재 네 문서는 루트에 있다. 이 문서는 구현 계획이며 기존 명세를 대체하지 않는다. 아래의 **제안**과 **팀 확정 필요** 항목은 아직 확정 요구사항이 아니다.

## 사용자 확정사항 및 참고 이미지 (2026-09-22 추가)

`recipe_img/recipe_1.jpg`, `recipe_2.jpg`, `recipe_3.jpg`를 확인했다. 사진에서 Mother의 왼쪽부터 H1~H5로 해석하면 아래 사용자 지정 조합과 일치한다. 사진의 Part들은 Mother에서 같은 쪽으로 뻗어 있다.

| Recipe | 요구 조립 |
|---|---|
| recipe_1 | H1: bolt_1 + part_2hole; H4: bolt_2 + part_3hole |
| recipe_2 | H1: bolt_1 + part_2hole; H3: bolt_1 + part_2hole |
| recipe_3 | H2: bolt_2 + part_3hole |

H5는 조립에 사용하지 않는다. 단, 이것이 H5의 검사를 제외한다는 뜻인지는 미확정이다. 금지 위치 조립을 검사하려면 H5 Anchor/ROI도 유지해야 한다. 위 나열은 요구 조합의 확정이며 작업 순서 확정으로 간주하지 않는다. 실제 3종의 모든 요구 조립은 Part를 포함하므로 `part: null`은 당장 필수 결정이 아니다.

H5 미사용 규칙만으로 대칭 Mother OBB의 방향이 결정되지는 않는다. 예를 들어 recipe_3의 실제 H4 오조립을 반대 방향으로 번호 매기면 H2 정상 조립으로 해석할 수 있고, 두 해석 모두 H5가 비어 있다. Recipe에 맞는 방향을 선택하는 것으로 방향 검증을 대체하지 않는다. 빈 Mother 초기 방향 기준 또는 물리적 비대칭 근거는 별도로 필요하다. Part의 돌출 방향을 기준으로 Hole 번호를 정의할 수도 있지만, 이는 기존의 Mother 고유 번호 기준과 의미가 달라지므로 사용자 합의가 필요하다.

Hole 비율/ROI는 반드시 사용자가 실물 길이를 재야 하는 값은 아니다. 최종 카메라 영상에서 Mother OBB와 Hole 중심, Bolt/Part 외곽을 지정해 정규화 비율을 산출할 수 있다. 현재 사진은 초기 추정에 활용 가능하지만 가림과 원근이 있으므로 최종 보정값으로 확정하지 않는다. 빈 Mother 영상 및 실제 모델 OBB와 함께 보정하고, ROI 여유와 overlap 임계값은 검증 영상으로 조정한다.

코드 구현 전 남은 운영 결정: 초기 방향 기준, Recipe 내 작업 순서 강제 여부, Part 각도 허용 범위, 미사용 Hole의 추가 부품 처리, 작업 대기와 누락 검사를 구분하는 검사 시작 조건. 기하 단위 테스트와 데이터 계약 등은 이 결정에 독립적으로 개발 가능하다.

## 1. 프로젝트 이해와 담당 범위

프로젝트는 **Vision-Based Poka-Yoke Assembly Verification System**이다. 고정 USB 카메라와 하나의 YOLO OBB 모델로 5개 클래스(`mother_part`, `bolt_1`, `bolt_2`, `part_2hole`, `part_3hole`)를 검출한다. 작업 중 이동·회전하는 Mother의 Hole H1~H5에 어떤 Bolt와 Part가 연결되어 있는지 추정하고, 외부 설정으로 관리하는 3개 Recipe의 조립 순서·종류·위치와 비교하여 실시간 피드백한다.

담당 범위는 엄밀히 말해 **Geometry + Association + Inspection + Temporal Filter + State Machine**이다. 이 전체를 `state_machine.py` 하나에 구현하지 않는다.

```text
정규화된 모델 검출값
  → Mother 방향 및 로컬 좌표계
  → H1~H5와 Bolt/Part ROI
  → 검출 객체를 Hole에 연결
  → 현재 조립 상태와 Recipe 비교
  → 시간 기반 판정 확정
  → 공정 상태 전이 및 이벤트 출력
```

카메라·모델 학습/추론은 Vision 담당과, 화면·DB·Arduino는 각 담당과 인터페이스로 연결한다. 이번 담당 코어는 이미지나 GPU가 없어도 실행·테스트할 수 있어야 한다. OBB/ROI의 공간적 일치는 조립 상태의 시각적 근거이며, 실제 볼트 체결력이나 Part의 첫 번째 Hole 결합 자체를 직접 측정하는 것은 아니다.

## 2. 구현 전에 확정할 사항

| 항목 | 필요한 결정 | 미확정 상태의 개발 방법 |
|---|---|---|
| Mother 방향 | H1→H5 및 +v의 물리적 기준, 180° 구분 방법 | 합성 데이터에 명시적 방향을 넣어 기하·공정 로직 개발 |
| 기하 보정 | Hole 비율, ROI 크기/오프셋, 적용 촬영 조건 | 테스트 전용 값과 실측 설정을 구분 |
| Recipe | 실제 3종 조합, 순서, `part: null` 의미 | 예시 Recipe는 테스트 fixture로만 사용 |
| 검사 시작·누락 | 작업 대기와 누락 오류를 구분할 조건 | 명시적 검사 요청/작업 타임아웃 등의 정책을 설정 가능하게 설계 |
| 순서·완료 이력 | 선행 조립 발견 시 처리, 통과 단계의 부품 제거 시 처리 | 아래 제안으로 테스트 작성, 실제 운영 전 합의 |
| 모델 출력 계약 | 좌표 복원, 각도/꼭짓점 규약, 클래스 매핑, timestamp | 정규화 DTO와 샘플 프레임으로 연동 합의 |

**방향 권고:** 물리적으로 가능한 경우 기준 마커 또는 비대칭 특징을 우선 검토한다. 마커를 선택하면 기존 5클래스 OBB 출력 외에 방향 근거를 전달하는 경로가 필요하다. 별도 딥러닝 모델을 기본 전제로 추가하지 않는다. 초기 방향 지정+추적을 선택하면 초기화 절차와 유실 후 재초기화가 필수다. 대칭 OBB의 연속성만으로 임의의 최초 방향이나 가림 중 180° 회전을 알아낼 수는 없다.

방향 확정 전에는 `orientation_valid=false`로 표현하고 Hole 번호 기반 PASS를 허용하지 않는다. 이 제약을 숨긴 채 0~360° 대응을 완료했다고 판단하지 않는다.

## 3. 권장 디렉토리와 파일 분리

아래는 향후 구현 구조다. 기존 명세의 `src/app`, `vision`, `geometry`, `process` 구성을 유지하고 공용 데이터 계약만 `contracts`로 분리한다. 지금 모든 폴더를 빈 파일로 만들 필요는 없으며 개발 단계에 맞춰 추가한다. 각 Python 패키지에는 `__init__.py`를 둔다.

```text
poka_yoke/
├── agent.md
├── system_overview.md
├── technical_specification.md
├── verification_specification.md
├── state_machine_development_guidelines.md
├── pyproject.toml
├── config/
│   ├── mother_geometry.yaml
│   ├── roi.yaml
│   ├── process.yaml
│   └── recipes/                 # 팀에서 확정한 3개 JSON
├── src/
│   ├── contracts/
│   │   ├── detections.py        # OBBDetection, DetectionFrame
│   │   └── inspection.py       # 공용 결과/이벤트 DTO, 오류 코드
│   ├── vision/
│   │   └── detection_adapter.py # Vision 담당: 모델 결과 → DetectionFrame
│   ├── geometry/
│   │   ├── types.py             # MotherPose, HoleAnchor, ROI, Association
│   │   ├── mother_frame.py      # 장·단축 정규화, 좌표 변환
│   │   ├── orientation.py       # 방향 근거 적용, 연속성/유효성 관리
│   │   ├── pose_filter.py       # Mother pose smoothing 및 유실 처리
│   │   ├── hole_estimator.py    # H1~H5 계산
│   │   ├── roi_builder.py       # Bolt 및 타입별 Part ROI 생성
│   │   ├── spatial.py           # 점 포함, 다각형 교차 면적, 거리
│   │   └── association.py       # 검출과 Hole 연결, 충돌/모호성 반환
│   ├── process/
│   │   ├── types.py             # Recipe, Step, HoleAssemblyState, 후보 판정
│   │   ├── recipe.py            # JSON 로드 및 의미 검증
│   │   ├── assembly.py          # Association → Hole별 관측 상태
│   │   ├── evaluator.py         # 기대/관측 비교; 공정 상태 변경 없음
│   │   ├── temporal.py          # 시간 기반 후보 판정 안정화
│   │   └── state_machine.py     # 상태, 현재 Step, 전이, 이벤트 생성
│   ├── app/
│   │   ├── config.py            # 설정 로드/검증
│   │   └── inspection_service.py # 한 프레임 처리와 외부 명령 연결
│   ├── database/               # 다른 담당: 이벤트 저장
│   ├── hardware/               # 다른 담당: LED/Buzzer
│   └── ui/                     # 다른 담당: 결과와 overlay 표시
├── scripts/
│   └── replay_detections.py     # JSONL 검출 기록 재생 및 결과 출력
└── tests/
    ├── fixtures/               # 합성 프레임, 예시 Recipe, 시간 시퀀스
    ├── unit/                   # geometry/process 결정론적 테스트
    └── integration/            # 여러 프레임 → 공정 완료/오류 회복
```

책임 경계:

- `geometry`는 실제 위치와 연결 가능성을 계산한다. Recipe에 맞추려고 검출 클래스를 바꾸거나 후보를 숨기지 않는다.
- `evaluator`는 관측과 Recipe를 비교한다. Step 증가, DB 저장, 화면 갱신은 하지 않는다.
- `temporal`은 동일한 의미의 판정이 충분히 유지됐는지 판단한다. 좌표의 미세한 변화 자체를 후보 변경으로 보지 않는다.
- `state_machine`만 현재 Step과 공정 상태를 변경한다. ROI 수식이나 YOLO 호출을 넣지 않는다.
- `inspection_service`는 모듈을 호출하고 결과를 모은다. 핵심 판정 규칙은 각 모듈에 둔다.

Python 3.11+, dataclass, type hint를 사용한다. 코어는 표준 라이브러리/NumPy와 필요한 기하 연산 정도로 구성하고, OpenCV는 polygon 연산 등에 제한적으로 사용할 수 있다. 코어 import에 Ultralytics, Streamlit, serial, DB 초기화가 따라오지 않게 한다. 의존성 버전은 실제 연동 시 검증 후 고정한다.

## 4. 데이터 계약을 가장 먼저 만든다

| 데이터 | 필수 내용 |
|---|---|
| `DetectionFrame` | frame_id, 단조 증가하는 capture timestamp, 원본 영상 크기, detections, 입력 유효 상태, 선택적 방향 근거 |
| `OBBDetection` | 프레임 내 detection_id, class_id/name, confidence, center_xy, width/height, angle_rad, polygon_xy |
| `MotherPose` | C, W/H, u/v, 방향 유효성, 최신 관측 시간, stale 여부 |
| `Association` | hole_id, 후보 detection_id, 거리/overlap, MATCHED/UNMATCHED/AMBIGUOUS 및 근거 |
| `HoleAssemblyState` | hole_id, 관측 Bolt/Part와 confidence, overlap, 관측 품질 |
| `InspectionCandidate` | PASS/NG/PENDING/UNKNOWN, 오류 목록, 관련 Hole, expected/observed, 판정 근거 |
| `InspectionSnapshot` | run_id, recipe_id, step_id, FSM 상태, 현재 후보/확정 판정, 최신성, overlay geometry |
| `InspectionEvent` | event_id, 시각, 상태 전이, Recipe/Step, 기대/관측값, 근거 및 latency |

`PENDING/UNKNOWN`과 관측 품질 필드는 기존 명세를 구체화하기 위한 제안이다. `None` 하나로 “아직 안 놓음”, “검출되지 않음”, “가려서 모름”을 전부 표현하지 않는다. OBB 출력만으로 가림 여부를 확실히 구분할 수 없으므로 관측 품질 판단의 한계도 기록한다.

좌표·시간 규약:

1. 좌표는 원본 영상 pixel, x는 오른쪽, y는 아래쪽이다. 모델 입력 resize/letterbox 역변환은 adapter에서 완료한다.
2. angle은 radian이다. 내부에서 Mother의 W는 장축, H는 단축으로 정규화한다. width/height 교환 시 각도도 함께 보정한다.
3. polygon은 자기 교차 없는 일정한 순서의 4개 꼭짓점이며 center/크기/각도와 일치해야 한다. 라이브러리 고유 각도 범위를 코어에 노출하지 않는다.
4. 시간 안정화는 wall clock이 아닌 같은 clock domain의 단조 timestamp를 사용한다. 실제 로그의 UTC 시각은 별도로 보관한다.
5. 역순/중복 frame, NaN, 음수 크기, 면적 0, 알 수 없는 클래스는 입력 경계에서 처리한다. Mother 후보가 여러 개면 임의로 갈아타지 않고 선택 정책 또는 모호 상태를 적용한다.

외부 API 제안은 `load_recipe(...)`, `update(frame) -> (snapshot, events)`, `request_verify(...)`, `reset(...)`이다. 카메라 장애 등 외부 오류를 전달하는 경로도 둔다. 테스트에서는 timestamp를 직접 주입하여 `sleep()` 없이 실행한다.

## 5. Geometry 구현 규칙

### 5.1 Mother 로컬 좌표계

방향이 결정된 θ에 대해:

```text
u = (cos θ, sin θ)
v = (-sin θ, cos θ)
image(a, b) = C + a·W·u + b·H·v
a = dot(point - C, u) / W
b = dot(point - C, v) / H
Hole_i = image(alpha_i, beta_i)
```

기술 명세의 수식을 사용한다. 개요의 축약식에 W/H 스케일이 생략되어 있으므로 그대로 pixel 수식으로 구현하지 않는다. 기본적으로 beta는 공통값을 써도 되며, Hole별 beta는 실제 보정 필요가 있을 때 사용한다.

주의: 영상 y가 아래로 증가하므로 이 정의에서 θ=0의 +v는 화면 아래다. 문서의 “위로 향하는 +v” 그림을 화면 규칙으로 해석하지 않는다. 물리적 Part 부착 방향과 이 축 규약이 맞는지 보정 이미지로 확인하여 확정한다.

중심/크기는 EMA, 방향 확정 이후 각도는 sin/cos 기반 smoothing을 적용한다. 빠른 이동 시 smoothing 지연으로 ROI가 뒤처질 수 있으므로 파라미터와 최대 pose age를 검증한다. 유실 pose를 표시용으로 잠깐 유지할 수는 있지만 stale pose로 새 PASS를 확정하지 않는다.

### 5.2 Bolt ROI

H_i를 중심으로 half-width=`r_w·W`, half-height=`r_h·H`인 로컬 사각형을 만들고 네 꼭짓점을 영상 좌표로 변환한다. Bolt 중심의 로컬 거리와 경계 포함 여부로 판정한다. 화면 정렬 bbox로 대체하지 않는다.

### 5.3 Part ROI

단위 혼동을 막기 위한 **제안 규약**:

```text
width_px  = width_ratio  · W     # u 방향 전체 폭
length_px = length_ratio · W     # v 방향 전체 길이
offset_px = offset_ratio · W    # Anchor에서 ROI 중심까지
P_i = H_i + offset_px · v
```

Part 길이/offset도 같은 Mother 장축 W를 기준으로 정규화한다는 제안이다. 기존 명세는 이 기준 길이를 확정하지 않았으므로 설정 설명에 반드시 남긴다. half-size와 전체 크기도 구분한다. 실제 값은 실측으로 결정한다.

H1~H5 각각에 두 Part 타입의 ROI를 만들 수 있게 한다. 기대 타입의 ROI만 만들거나 기대 클래스만 검사하면 `WRONG_PART`가 `MISSING_PART`로 잘못 분류될 수 있다. 이미지를 잘라 새 모델에 넣는 방식이 아니라, 기존 OBB와 동적 polygon을 비교하는 방식이 기본이다. 이미지 crop은 필요 시 디버그 표시용이다.

## 6. Association과 Recipe 비교

### 6.1 공간 연결

- Bolt: 중심이 포함된 ROI를 후보로 잡는다. 여러 Hole에 걸리면 정규화 거리와 후보 간 차이를 본다. 근거가 부족한 경우 AMBIGUOUS로 남긴다. 거리 기반 fallback은 최대 거리 제한과 함께 설정한다.
- Part: `intersection_area(part_obb, part_roi) / area(part_obb)`를 쓴다. IoU와 다른 지표다. 각 검출 클래스에 해당하는 ROI 형상으로 후보를 평가하고, 기대 클래스 비교는 그 다음에 한다.
- 한 검출을 여러 Hole의 부품으로 중복 사용하지 않는다. 같은 Hole의 같은 부품 슬롯에 여러 검출이 경쟁하는 경우도 해결하거나 모호 상태로 반환한다. MVP에서는 결정론적인 후보 점수·차이 기준으로 시작한다.
- ROI 밖의 부품을 무조건 오류로 보지 않는다. 작업대 대기 부품과 잘못된 Hole에 놓인 부품을 구분할 공간적 근거가 필요하다.
- Part OBB overlap만으로 실제 첫 Hole 결합을 증명할 수 없다. 인접 Anchor의 ROI가 많이 겹치는 경우 검증 데이터를 통해 한계를 확인하고, 필요할 때만 추가 anchor 근거를 검토한다.

### 6.2 프레임 판정

| 관측 | 후보 판정 원칙 |
|---|---|
| 기대 Hole에 기대 Bolt/Part 연결 | PASS 후보 |
| 기대 Hole에 다른 Bolt | WRONG_BOLT |
| 기대 Anchor에 다른 Part | WRONG_PART |
| 해당 작업과 연결 가능한 부품이 다른 Hole에 배치됨 | WRONG_POSITION |
| 검사 조건 성립 후 요구 부품이 지속적으로 미검출 | MISSING_BOLT / MISSING_PART 후보 |
| 미래 Step 조립이 먼저 안정적으로 확인됨 | 합의한 순서 정책에 따라 SEQUENCE_ERROR |
| Mother 유실·방향 불명·연결 모호·오래된 입력 | UNKNOWN; 새 PASS/Step 진행 금지 |
| 작업 전이고 요구 부품을 아직 놓지 않음 | PENDING; 즉시 누락 NG로 바꾸지 않음 |

같은 Bolt 타입이 여러 Step에 쓰일 수 있으므로 다른 Hole에 동일 클래스가 있다는 이유만으로 현재 Step의 `WRONG_POSITION`을 확정하지 않는다. 완료된 Step의 정상 부품인지, 미래 Step의 선행 조립인지, 현재 작업의 잘못된 배치인지 전체 상태를 비교한다. 구분되지 않으면 모호성을 유지한다.

여러 오류는 목록으로 보존하고 UI 대표 오류 선정은 별도 정책으로 둔다. 기존 E001~E501 매핑을 유지한다. 시스템 입력 장애와 공정 NG를 구분한다.

`part: null`은 **팀 확정 필요**다. “Part 없어야 함”인지 “검사 제외”인지 문서만으로 단정하지 않는다. 구현에서는 두 의미를 구분할 수 있게 하고 실제 Recipe의 해석을 명시한다. 반복 Hole 사용이나 같은 Hole의 재작업도 임의로 허용/금지하지 않고 Recipe 검증 정책에 반영한다.

## 7. Temporal Filter와 상태 전이

### 7.1 시간 기반 안정화

기본 제안값은 명세 범위 내 400 ms다. 설정은 `stable_duration_ms`, 허용 frame gap, pose 유효시간, 누락 검사 조건을 구분한다. 튜닝은 Validation에서 하고 Test에서는 고정한다.

- 후보 key는 Recipe/Step, 결과, 오류 종류, 관련 Hole/관측 클래스 등 의미값으로 만든다. 좌표와 confidence 실수값 전체를 key로 쓰지 않는다.
- 최초 프레임 한 장이나 같은 프레임의 재처리로 확정하지 않는다. 허용 frame gap 내의 여러 유효 관측이 안정화 시간을 충족해야 한다.
- UNKNOWN 구간은 PASS 증거 시간에 더하지 않는다. 보수적인 초기 구현은 후보 타이머를 취소한다. 마지막 확정 표시와 현재 유효 여부는 분리한다.
- 짧은 검출 누락은 즉시 새 NG를 확정하지 않는다. 장시간 입력 단절 뒤 프레임이 돌아왔다고 단절 시간을 안정화 시간에 포함하지 않는다.
- Step 전환, Recipe 변경, reset 시 후보를 초기화한다. 이전 Step의 확정값을 다음 Step으로 재사용하지 않는다.

### 7.2 상태 머신 제안

| 현재 상태 | 조건/명령 | 다음 상태 및 처리 |
|---|---|---|
| IDLE | Recipe 선택 | LOAD_RECIPE |
| LOAD_RECIPE | 유효 Recipe 로드 | WAIT_STEP; run/step 초기화 |
| LOAD_RECIPE | 잘못된 Recipe | SYSTEM_ERROR / INVALID_RECIPE |
| WAIT_STEP | 검사 시작 조건 성립 | VERIFY_STEP |
| VERIFY_STEP | 안정 PASS | STEP_PASS; 이벤트 1회 |
| VERIFY_STEP | 안정 NG | STEP_ERROR; 현재 Step 유지 |
| STEP_ERROR | 수정 관측 후 재검증 시작 | VERIFY_STEP; 안정화 재시작 |
| STEP_PASS | 남은 Step 존재 | WAIT_STEP; Step 1회 증가 |
| STEP_PASS | 마지막 Step 및 전체 최종 조건 충족 | PRODUCT_COMPLETE; 완료 이벤트 1회 |
| 활성 상태 | 검사 불가 시스템 장애 | SYSTEM_ERROR; Step 진행 중지 |
| SYSTEM_ERROR | 원인 해소 및 재개 조건 충족 | WAIT_STEP; 신선한 관측으로 재검증 |
| PRODUCT_COMPLETE | 명시적 새 제품/reset | IDLE 또는 새 run의 LOAD_RECIPE |

`UNKNOWN`은 공정 FSM 상태를 무조건 바꾸는 명령이 아니라 관측 품질이다. 짧은 유실은 진행을 보류하고, 설정된 장애 지속시간을 넘으면 SYSTEM_ERROR로 전환한다. 자동 복구 가능 오류와 Recipe 재선택 등 명시적 조치가 필요한 오류를 구분한다.

**운영 정책 제안:** 완료 Step도 계속 재검증한다. 부품 제거/변경이 안정적으로 확인되면 진행을 막고 해당 Hole 오류를 출력한다. 완료 이력과 현재 관측은 별개로 관리한다. 마지막 Step만 맞는다고 완료 처리하지 않고, 전체 요구 조립이 같은 유효 관측 구간에서 안정적으로 일치해야 한다. 실제 rollback/재작업 UX는 팀에서 확정한다.

순서 위반은 오류 발견 시점과 해결 조건까지 정의한다. 이미 모두 조립된 제품을 처음 보여주는 것으로 정상 순서를 수행했다고 간주하지 않는다. 최종 검사 모드가 필요하면 순서 검사와 별도 모드로 합의한다.

## 8. 개발 순서와 단계별 완료 조건

| 단계 | 구현 내용 | 다음 단계로 넘어가는 기준 |
|---|---|---|
| 0. 계약·정책 | DTO, 좌표/시간 규약, 미확정 항목 정리 | 모델 담당과 샘플 출력 합의, 임시값 명시 |
| 1. 기반 | 패키지 설정, config/Recipe loader, 합성 fixture | 정상/오류 설정 테스트 통과; 실제 Recipe로 오인할 예시 없음 |
| 2. 좌표계 | Mother 정규화, 방향 interface, 양방향 변환, Hole | 회전/이동 후 H1~H5 일관성 및 round-trip 테스트 통과 |
| 3. ROI | Bolt/Part polygon, 디버그 출력 | 전체 각도에서 +v 및 크기 검증 |
| 4. 연결 | Bolt/Part association, 모호성 처리 | 중복 연결·다중 후보·잘못된 타입/위치 테스트 통과 |
| 5. 비교 | Hole 관측 상태, Recipe evaluator | PASS/주요 NG/PENDING/UNKNOWN을 프레임 단위로 재현 |
| 6. 안정화 | timestamp 기반 filter | transient, frame gap, jitter, FPS 변화 테스트 통과 |
| 7. FSM | Step 전이, 오류 수정, 완료/reset | 정상 전체 run·NG 복구·중복 이벤트 방지 통과 |
| 8. 실제 연동 | 정규화 모델 출력 재생 → 실시간 연결 | 좌표/각도 계약 검증, 실제 방향 해결·기하 보정 완료 |
| 9. 통합 검증 | UI/로그 전달, 정량 평가 | 기존 검증 명세의 담당 지표와 통합 결과 보고 |

우선순위는 **완벽한 FSM을 먼저 만드는 것보다, 합성 검출값 → Hole/ROI → 연결 결과를 먼저 검증하는 것**이다. 잘못된 Geometry 위의 FSM은 공정 규칙이 정확해도 잘못된 판정을 안정적으로 확정하게 된다.

최초 개발 묶음은 `contracts`, config/Recipe loader, 테스트 fixture와 `mother_frame`/`hole_estimator`까지로 작게 잡는다. 이후 각 단계마다 구현과 결정론적 테스트를 함께 추가한다. 모델 학습 완료를 기다릴 필요는 없다. 단, 실제 방향 해결과 보정은 통합 완료의 필수 조건이다.

## 9. 테스트 및 디버깅 기준

필수 자동 테스트:

- 0°, 30° … 330°의 좌표 변환, 180° 후 물리적 Hole 번호 유지, 359°↔0° 연속성, width/height 교환.
- 이동/스케일 변화, ROI 경계점, 겹치지 않는 polygon, 면적 0, overlap 임계값 전후.
- 한 객체가 두 ROI와 겹침, 한 Hole에 두 객체, 기대와 다른 Part 검출, 작업대의 무관한 부품.
- 빈 작업 시작, 검사 요청 후 누락, 순간 miss, Mother 유실, 재등장 시 방향 불명, 오래된 frame.
- 안정화 시간 직전/직후, 한 프레임만 입력, 중복/역순 시간, 긴 frame gap.
- 정상 Step 진행, NG 수정 후 복구, 선행 조립, 이전 Step 부품 제거, reset/Recipe 변경, 완료 이벤트 중복 방지.

합성 테스트는 기하·공정 로직의 정확성 검증이며 실제 검출 성능 증거가 아니다. 실제 데이터로 별도 평가한다. 재생 기록에는 원본 timestamp와 검출값, 설정 버전, Recipe 버전을 남겨 같은 입력이 같은 결과를 내도록 한다.

overlay에는 Mother u/v, H1~H5, Bolt ROI, 타입별 Part ROI, 연결선, overlap/거리, 후보와 확정 판정, pose 최신성을 표시한다. 추론 오류인지 기하 오류인지 공정 오류인지 추적할 수 있게 한다. 이벤트에는 기존 명세의 timestamp, recipe_id, step_id, mother_pose, expected/detected, result, confidence, latency를 포함한다. 전체 프레임 기록과 상태 전이 이벤트는 분리하여 매 프레임 같은 NG 이벤트를 쌓지 않는다.

원문 기준의 주요 목표:

| 대상 | 초기 목표 |
|---|---|
| Mother 방향 오차 | median ≤ 3°, p95 ≤ 7°; 방향 모호성 해결 후 측정 |
| Hole 정규화 오차 | mean ≤ 0.03, p95 ≤ 0.06 |
| Bolt-to-Hole / Part Anchor 연결 | 각각 ≥ 95% |
| 주요 NG 검출 / 정상 수락 | ≥ 95% |
| False Alarm | ≤ 5% |
| 전체 피드백 지연 | median ≤ 1.0초, p95 ≤ 1.5초; 안정화 포함 |
| 통합 처리 FPS | 평균 ≥ 10 |

위 목표는 검증 명세의 초기 기준이며 이 문서에서 변경하지 않는다. 실제 3종 Recipe, 회전·이동·가림, 총 210회 권장 E2E trial 및 30 product run의 중요 로그 누락 0 기준은 원문을 따른다. 검출 지표/전체 FPS는 다른 담당과 함께 검증한다.

## 10. 이번 문서의 적용 범위

이번 작업은 로컬 개발 가이드 작성이다. 기존 네 명세는 이동하거나 수정하지 않는다. 향후 소스 구현은 이 가이드의 단계별 범위로 진행하며, 실제 Recipe와 미확정 운영 정책을 확정값처럼 코드에 넣지 않는다. 원격 브랜치 `seungjae/state_machine`에 대한 commit/push 및 PR 생성은 이 문서 작성에 포함하지 않는다.
