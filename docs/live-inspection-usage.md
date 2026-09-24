# 라이브 조립 검사 실행 방법

RT-DETR로 부품을 검출하고, 재료 확인 → 조립 검사(H1~H5 구멍별 볼트/부품 배치)를 한글 화면으로 안내하는 앱.

- 실행 파일: `scripts/live_inspection.py`
- 구성: 카메라/영상 → RT-DETR(`src/vision/rtdetr_adapter.py`가 mother 각도 복원) → 판정 엔진(`InspectionService`) → 한글 HUD(`src/app/hud.py`)

## 1. 준비

- conda 환경 `vision_programming` 활성화 (ultralytics, opencv, pillow 설치됨)
- 가중치: `runs/rtdetr/full_run/weights/best.pt` (3차 실험, 980장 학습) — 기본값
- 카메라: 검은 배경 위, 탑다운, 조립체를 화면 안에 통째로 넣기
- **저장소 루트에서 실행** (`python -m`으로 실행해야 `src` 패키지를 찾음)

## 2. 실행

### C270 (USB 웹캠)

```
python -m scripts.live_inspection --camera 3 --recipe 3
```

배경이 회색으로 뜨면(자동노출 때문) 셔터 속도를 고정:

```
python -m scripts.live_inspection --camera 3 --recipe 3 --exposure 1/20
```

### DroidCam (폰 카메라)

폰 앱 실행 → PC 클라이언트에서 Start(WiFi 또는 USB) 후:

```
python -m scripts.live_inspection --camera 1 --backend msmf --droidcam-watermark --recipe 3
```

- DroidCam은 DirectShow에는 안 잡히고 **MSMF 백엔드**로만 잡힘 (`--backend msmf`)
- `--droidcam-watermark`: 무료 버전이 프레임에 박는 "using droidcam.app" 글자를 지우고 추론 (640x480 기준 위치)
- 카메라 인덱스는 PC 상태에 따라 바뀜 → 안 열리면 아래 "카메라 인덱스 찾기" 참고

### 영상 파일로 (카메라 없이 테스트)

```
python -m scripts.live_inspection --video 1.mp4 --recipe 3
```

결과를 mp4로 저장하고 창 없이 돌리기:

```
python -m scripts.live_inspection --video 1.mp4 --recipe 3 --save-video runs/inspection_demo/out.mp4 --no-window
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
| `--weights` | `runs/rtdetr/full_run/weights/best.pt` | RT-DETR 가중치 |
| `--conf` | config의 `confidence_threshold`(0.5) | 검출 confidence |
| `--config` | `config/rtdetr_live.json` | 판정 설정 (아래 참고) |
| `--camera` | 0 | 카메라 인덱스 |
| `--backend {dshow,msmf}` | dshow | 카메라 백엔드 |
| `--width` / `--height` | 1280 / 720 | 요청 해상도 |
| `--exposure` | (자동) | 셔터 속도 수동 고정, 예: `1/20` |
| `--droidcam-watermark` | 꺼짐 | DroidCam 워터마크 제거 |
| `--video` | (없음) | 카메라 대신 영상 파일 |
| `--save-video` | (없음) | HUD 포함 결과를 mp4로 저장 |
| `--no-window` | 꺼짐 | 창 없이 실행 (콘솔 로그/저장만) |
| `--max-frames` | 0 | 처리할 최대 프레임 (0=끝까지) |

## 6. 판정 설정 (`--config`)

| 파일 | 특징 |
|---|---|
| `config/rtdetr_live.json` (기본) | mother 각도 한계 89.9°, 세로 부품이 mother 아래쪽에 붙어도 인식(`allow_parts_below`), 좌우 뒤집힌 구멍 번호 허용(`allow_mirrored_holes`) |
| `config/mvp.json` (팀원 원본) | 각도 ±15°, 부품은 mother 위쪽만, H1은 화면 왼쪽 고정 |

- 정답을 아는 조립 사진 100장 기준 정상(PASS) 판정: `mvp.json` 61장 → `rtdetr_live.json` 98장
- 다른 모델 레시피 / 구멍 위치만 틀린 레시피로 검사한 300건은 PASS 0건 (오통과 없음)
- 수치는 학습에 쓴 사진 기준이라 실제 카메라에서는 더 낮을 수 있음
- 팀원 원래 동작이 필요하면 `--config config/mvp.json`

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

### 9-4. RT-DETR 테스트셋 추론

test 셋(`data/aabb/images/test`) 전체에 박스+클래스+confidence를 그려 저장:

```
python src/detection/rt-detr/test_full_val.py
python src/detection/rt-detr/test_full_val.py --weights runs/rtdetr/full_run/weights/best.pt --conf 0.5
```

- 기본 출력: `runs/rtdetr_test/full_run/`
- 옵션: `--images --weights --output --conf(기본 0.25)`

### 9-5. 영상으로 라이브 앱 스모크 테스트 (카메라 없이)

앞부분 300프레임만 창 없이 돌려 콘솔 로그로 상태 흐름 확인:

```
python -m scripts.live_inspection --video 1.mp4 --recipe 3 --no-window --max-frames 300
```

HUD 결과 영상까지 저장해 눈으로 확인:

```
python -m scripts.live_inspection --video 2.mp4 --recipe 1 --no-window --save-video runs/inspection_demo/2_out.mp4
```

- 콘솔에 `[시간] 단계 | 상태 | stable | 이슈` 줄이 상태 변화 때마다 찍힘
- 마지막 줄 `[INSPECT] 종료 — N프레임 처리`가 나오면 파이프라인이 끝까지 돈 것

### 9-6. 룰베이스(구멍 개수) 라이브/촬영 — 카메라 필요

```
python src/rule_based/live_hole_check.py --camera 3 --exposure 1/20
python src/rule_based/capture_hole_check.py --camera 3 --output runs/rule_based_photos --tag model_c
```

- `Result`(판정)와 `Debug`(회전 보정 + 볼트 색상 근거) 두 창이 뜸
- 촬영 스크립트는 `s`키로 두 창을 PNG로 저장, `q` 종료

### 권장 순서

1. `python -m pytest tests -q` — 코드가 안 깨졌는지 (카메라/모델 없이 수 초)
2. `--video 1.mp4 ... --no-window` — 모델+파이프라인 연결 확인
3. 실제 카메라로 `scripts.live_inspection` — 최종 확인

## 관련 스크립트

| 스크립트 | 용도 |
|---|---|
| `src/detection/rt-detr/live_test.py` | RT-DETR 검출 결과만 실시간으로 보기 (`--camera`, `--backend`, `--weights`, `--droidcam-watermark`) |
| `src/rule_based/live_hole_check.py` | 구멍 개수 룰베이스로 Model A/B/C 분류 (`--exposure`, `--backend`, `--droidcam-watermark`) |
| `src/rule_based/capture_hole_check.py` | 위와 같은 화면에서 `s`키로 발표용 사진 저장 (`--output`, `--tag`) |
