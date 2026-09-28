# 라이브 조립 검사 실행 방법

RT-DETR로 부품을 검출하고, 재료 확인 → 조립 검사(H1~H5 구멍별 볼트/부품 배치)를 한글 화면으로 안내하는 앱.

⚠️ **이 브랜치(taein/mother-registration) 안내**: 이 문서와 `scripts/live_inspection_rtdetr.py`는
experiment/rt-detr 브랜치의 "모델만 바꾸면 쓸 수 있는 라이브 테스팅 코드"만 정리해서 이름을 바꿔
그대로 옮긴 것이다. 이 브랜치 고유의 `scripts/live_inspection.py`(mother 등록/추적, 가림 기억,
배너·알림음)와는 별개 앱이며 서로 건드리지 않는다. `InspectionService`/`roi_builder.py`는 이 브랜치의
mother 등록 버전을 그대로 쓰므로, `config/rtdetr_live.json`의 `allow_parts_below`/
`allow_mirrored_holes` 완화 플래그는 여기서는 효과가 없다(그 엔진 수정은 experiment/rt-detr
전용) — 그래서 아래 기본 `--config`는 이 브랜치가 이미 튜닝해 둔 `config/mvp.json`이다.

- 실행 파일: `scripts/live_inspection_rtdetr.py`
- 구성: 카메라/영상 → RT-DETR(`src/vision/rtdetr_adapter.py`가 mother 각도 복원) → 판정 엔진(`InspectionService`) → 한글 HUD(`src/app/hud.py`)

## 1. 준비

- conda 환경 `vision_programming` 활성화 (ultralytics, opencv, pillow 설치됨)
- 가중치: `runs/rtdetr/full_run/weights/best.pt` (3차 실험, 980장 학습) — 기본값
- 카메라: 검은 배경 위, 탑다운, 조립체를 화면 안에 통째로 넣기
- **저장소 루트에서 실행** (`python -m`으로 실행해야 `src` 패키지를 찾음)

## 2. 실행

### C270 (USB 웹캠)

```
python -m scripts.live_inspection_rtdetr --camera 3 --recipe 3
```

배경이 회색으로 뜨면(자동노출 때문) 셔터 속도를 고정:

```
python -m scripts.live_inspection_rtdetr --camera 3 --recipe 3 --exposure 1/20
```

### DroidCam (폰 카메라)

폰 앱 실행 → PC 클라이언트에서 Start(WiFi 또는 USB) 후:

```
python -m scripts.live_inspection_rtdetr --camera 1 --backend msmf --droidcam-watermark --recipe 3
```

- DroidCam은 DirectShow에는 안 잡히고 **MSMF 백엔드**로만 잡힘 (`--backend msmf`)
- `--droidcam-watermark`: 무료 버전이 프레임에 박는 "using droidcam.app" 글자를 지우고 추론 (640x480 기준 위치)
- 카메라 인덱스는 PC 상태에 따라 바뀜 → 안 열리면 아래 "카메라 인덱스 찾기" 참고

### 영상 파일로 (카메라 없이 테스트)

```
python -m scripts.live_inspection_rtdetr --video 1.mp4 --recipe 3
```

결과를 mp4로 저장하고 창 없이 돌리기:

```
python -m scripts.live_inspection_rtdetr --video 1.mp4 --recipe 3 --save-video runs/inspection_demo/out.mp4 --no-window
```

## 3. 키 조작

| 키 | 동작 |
|---|---|
| `1` / `2` / `3` | 레시피 선택 (1=Model A, 2=Model B, 3=Model C), 상태 초기화 |
| `n` | 새 제품 (같은 레시피로 처음부터) |
| `q` | 종료 |

## 4. 화면 읽는 법

- 1행: `recipe_3 | 1. 재료 확인` 또는 `2. 조립 검사`
- 2행: 레시피 (예: `H2: 주황 볼트 + 3구 나무조각`)
- 3행: 상태 — 판정 대기 / 조립 중 / 정상(조립 완료) / 오류(NG), 안정화 중이면 `(확인 중)`
- 이후: 해야 할 일(노랑) 또는 오류 원인(빨강), 예: `H2: 주황 볼트를 끼워주세요`, `H4: 레시피에 없는 위치입니다 - 빼주세요`
- 박스: 클래스별 색 (mother 초록, 노랑 볼트 노랑, 주황 볼트 주황, 2구 하늘색, 3구 자홍)
- 링 `H1`~`H5`: 초록=정상, 노랑=아직 없음, 빨강=오류, 회색=레시피에 없는 자리
- 우하단 `mother 각도 ...`: 어댑터가 구한 각도와 출처 (`measured`/`held`/`fallback`)
- 하단: FPS와 키 안내

흐름: **재료 확인**에서 필요한 개수가 다 놓이면 안정화 후 **조립 검사**로 넘어가고, 구멍별 배치가 레시피와 맞으면 정상 판정.

## 5. 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--recipe {1,2,3}` | 1 | 시작 레시피 |
| `--model-type {rtdetr,yolo,yolo-obb}` | rtdetr | 검출 모델 종류 (아래 "모델 종류 바꾸기" 참고) |
| `--weights` | `--model-type`별 기본값 | 가중치 경로 |
| `--conf` | config의 `confidence_threshold`(0.5) | 검출 confidence |
| `--config` | `config/mvp.json` (이 브랜치 기본) | 판정 설정 (아래 참고) |
| `--camera` | 0 | 카메라 인덱스 |
| `--backend {dshow,msmf}` | dshow | 카메라 백엔드 |
| `--width` / `--height` | 1280 / 720 | 요청 해상도 |
| `--exposure` | (자동) | 셔터 속도 수동 고정, 예: `1/20` |
| `--droidcam-watermark` | 꺼짐 | DroidCam 워터마크 제거 |
| `--video` | (없음) | 카메라 대신 영상 파일 |
| `--save-video` | (없음) | HUD 포함 결과를 mp4로 저장 |
| `--no-window` | 꺼짐 | 창 없이 실행 (콘솔 로그/저장만) |
| `--max-frames` | 0 | 처리할 최대 프레임 (0=끝까지) |

## 5-1. 모델 종류 바꾸기 (`--model-type`)

| 값 | 로드 클래스 | 기본 가중치 | 각도 처리 |
|---|---|---|---|
| `rtdetr` (기본) | `ultralytics.RTDETR` | `runs/rtdetr/full_run/weights/best.pt` | AABB만 나와서 `rtdetr_adapter.py`가 mother 각도를 영상에서 복원 |
| `yolo` | `ultralytics.YOLO` (detect) | 없음 — `--weights` 필수 | rtdetr와 같은 AABB라 같은 어댑터 재사용 |
| `yolo-obb` | `ultralytics.YOLO` (obb) | `model/yolo_obb_parts.pt` | 결과에 각도가 이미 있어 복원 없이 그대로 사용 (CLAUDE.md 확정 메인 파이프라인) |

```
python -m scripts.live_inspection_rtdetr --model-type yolo-obb --camera 1 --recipe 3
python -m scripts.live_inspection_rtdetr --model-type yolo --weights runs/yolo/best.pt --camera 1
```

- 클래스 이름이 5클래스(`bolt_2, bolt_1, mother_part, part_3hole, part_2hole`)와 다르면 HUD 색상 매핑(`src/app/hud.py`)이 못 알아봄 → 같은 클래스 이름/개수로 학습된 가중치여야 함
- `yolo-obb`는 회전각을 다시 재는 과정이 없어 `rtdetr`/`yolo`보다 프레임당 더 빠르고, 우하단 각도 표시는 `obb`로 나옴

## 6. 판정 설정 (`--config`)

| 파일 | 특징 |
|---|---|
| `config/mvp.json` (이 브랜치 기본) | 이 브랜치의 mother 등록/추적, 가림 기억, 구멍 배정 로직이 실제로 쓰는 튜닝된 설정 |
| `config/rtdetr_live.json` | experiment/rt-detr 브랜치에서 만든 각도/방향 완화 설정. **이 브랜치의 InspectionService에는 `allow_parts_below`/`allow_mirrored_holes`를 읽는 코드가 없어 로드는 되지만 효과가 없다** — RT-DETR 검출 결과를 이 브랜치 엔진에 그대로 넣어 시험해보고 싶을 때만 참고용으로 사용 |

- experiment/rt-detr 브랜치에서 측정한 PASS 61→98/100 등 수치는 그 브랜치 전용 엔진 수정 기준이라 이 브랜치에는 적용되지 않음 (이 브랜치는 mother 등록/추적으로 별도 검증됨, `tests/test_mother_registration.py` 등 참고)

## 7. 문제 해결

### 카메라 인덱스 찾기

```
python -c "import cv2; [print(i, cv2.VideoCapture(i, cv2.CAP_DSHOW).isOpened()) for i in range(6)]"
```

DroidCam은 `cv2.CAP_MSMF`로 같은 방식으로 확인. 화면을 저장해서 어느 카메라인지 눈으로 확인하는 게 가장 확실함.

| 증상 | 확인 |
|---|---|
| `카메라를 열 수 없습니다` | 다른 프로그램(`live_hole_check.py`, 카메라 앱)이 카메라를 잡고 있는지, 인덱스/백엔드가 맞는지 |
| 화면이 검음 (DroidCam) | 폰 앱과 PC 클라이언트가 Start 상태인지 (연결 끊기면 검은 프레임) |
| 배경이 회색으로 뜸 | `--exposure 1/20` (C270 자동노출이 밝은 부품 기준으로 전체를 밝게 보정함) |
| 상태가 계속 `판정 대기` | 화면 문구 확인: `Mother가 보이지 않습니다`(mother 검출 실패), `프레임이 끊겼습니다`(처리 속도 부족) |
| `어느 구멍인지 불명확합니다` | 부품을 mother 구멍에 정확히 맞춰 놓기, 손으로 가리고 있지 않은지 |
| 각도가 `fallback`으로 나옴 | mother 구멍이 3개 이상 안 보임(손/볼트로 가림) → 각도를 0°로 가정 중 |
| 한글이 깨짐 | Windows 기본 폰트 `C:/Windows/Fonts/malgun.ttf` 필요 |

## 8. 참고

- 콘솔에도 상태가 바뀔 때마다 한 줄씩 출력됨: `[시간] 단계 | 상태 | stable | 이슈 목록`
- 처리 속도: 프레임당 RT-DETR 약 37ms + 어댑터 1.3ms + 엔진 0.1ms + 화면 그리기 13ms ≈ 20FPS (RTX 4050 Laptop)
- 테스트: 아래 "9. 테스트 실행 방법" 참고

## 9. 테스트 실행 방법

모든 명령은 **저장소 루트**에서 실행 (테스트가 `src.*`를 import함).

### 9-1. 자동 테스트 (pytest) — 카메라/GPU 불필요

전체 실행 (현재 74개):

```
python -m pytest tests -q
```

| 파일 | 개수 | 검증 내용 |
|---|---|---|
| `tests/test_mvp.py` | 31 | 팀원 엔진: 기하(mother 포즈, 구멍 ROI), 판정, 디바운스, 프레임 끊김 |
| `tests/test_material_workflow.py` | 13 | 재료 확인 → 조립 검사 단계 전환 |
| `tests/test_rtdetr_adapter.py` | 19 | RT-DETR 어댑터: mother 각도 복원, 45° 부근 치수, 부품 축, 중복 제거, 각도 hold/fallback |
| `tests/test_relaxed_orientation.py` | 11 | 완화 설정: 기본은 위쪽 부품/±15°/뒤집힘 불가 유지, 완화 시 허용, 잘못된 구멍·볼트는 여전히 NG |

파일 단위 / 특정 테스트만:

```
python -m pytest tests/test_rtdetr_adapter.py -q
python -m pytest tests/test_relaxed_orientation.py -v
python -m pytest tests -k "angle" -v
python -m pytest tests/test_mvp.py -x
```

- `-q` 간단히, `-v` 테스트별 결과, `-k 문자열` 이름 필터, `-x` 첫 실패에서 중단
- 어댑터/완화 테스트는 합성 이미지를 쓰므로 모델 가중치가 필요 없음

### 9-2. 엔진 재생 (팀원 스크립트) — 모델 불필요

가짜 검출 시나리오로 상태 흐름을 콘솔에서 확인:

```
python -m scripts.replay_detections --demo --recipe recipe_1
python -m scripts.replay_detections --demo --recipe recipe_3 --config config/rtdetr_live.json
python -m scripts.replay_detections --demo --recipe recipe_1 --output outputs/replay.jsonl
```

- `--recipe recipe_1|recipe_2|recipe_3`, `--config`(기본 `config/mvp.json`), `--output` 스냅샷 JSONL 저장
- `--input 파일.jsonl`: 정규화된 DetectionFrame JSONL을 재생 (`--demo`와 택일)

### 9-3. 사진으로 확인 (팀원 스크립트) — YOLO 가중치 필요

⚠️ 기본 모델 경로 `model/yolo_obb_parts.pt`가 저장소에 없으면 `--model`로 지정해야 함.

```
python -m scripts.verify_materials --recipe all
python -m scripts.visualize_rois --images sample_img --output outputs/roi_debug
```

- `verify_materials`: 재료 사진이 각 레시피 재료와 맞는지 검사 (`--recipe recipe_1|recipe_2|recipe_3|all`), 결과는 `outputs/material_debug/<시각>/`
- `visualize_rois`: 구멍/부품 ROI 오버레이 이미지 생성 (`--model --images --config --output --conf`)

⚠️ RT-DETR 학습/데이터셋 파이프라인(`test_full_val.py` 등)은 이 브랜치로 가져오지 않았음 — experiment/rt-detr 브랜치 전용.

### 9-4. 영상으로 라이브 앱 스모크 테스트 (카메라 없이)

앞부분 300프레임만 창 없이 돌려 콘솔 로그로 상태 흐름 확인:

```
python -m scripts.live_inspection_rtdetr --video 1.mp4 --recipe 3 --no-window --max-frames 300
```

HUD 결과 영상까지 저장해 눈으로 확인:

```
python -m scripts.live_inspection_rtdetr --video 2.mp4 --recipe 1 --no-window --save-video runs/inspection_demo/2_out.mp4
```

- 콘솔에 `[시간] 단계 | 상태 | stable | 이슈` 줄이 상태 변화 때마다 찍힘
- 마지막 줄 `[INSPECT] 종료 — N프레임 처리`가 나오면 파이프라인이 끝까지 돈 것

⚠️ 룰베이스(구멍 개수) 분류 스크립트(`live_hole_check.py`, `capture_hole_check.py`)도 이 브랜치로 가져오지 않았음 — experiment/rt-detr 브랜치 전용.

### 권장 순서

1. `python -m pytest tests -q` — 코드가 안 깨졌는지 (카메라/모델 없이 수 초)
2. `--video 1.mp4 ... --no-window` — 모델+파이프라인 연결 확인
3. 실제 카메라로 `scripts.live_inspection_rtdetr` — 최종 확인

## 이 브랜치의 다른 앱

이 브랜치 고유의 mother 등록/추적 기반 라이브 앱은 별도다 (`scripts/live_inspection.py`,
`scripts/live_registration.py`, `scripts/check_registration.py`) — 자세한 내용은
`docs/mother_registration.md` 참고.
