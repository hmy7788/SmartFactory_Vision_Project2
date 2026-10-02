# 실행 방법

AEGIS를 설치하고 돌리는 방법. 프로젝트 소개·아키텍처·결과는 [README](../README.md)를 본다.

## 0. 준비

| 항목 | 내용 |
|---|---|
| Python | 3.10+ — `pip install -r requirements.txt` (GPU torch는 따로: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126`) |
| Java | 17+ (Temurin 21) — MES 서버를 띄울 때만 |
| MQTT 브로커 | [Mosquitto](https://mosquitto.org/download/) Windows 설치판 — MES 연동 때만 |
| 가중치 | `weights/`에 둔다 (Git 제외, 팀 공유 드라이브). 목록은 [weights/README.md](../weights/README.md) |
| 경로 | 저장소는 **영문 경로**에 clone한다 — MES의 Gradle이 한글 경로에서 실패한다 (Windows 계정 이름이 한글이면 `mes/*.cmd`가 Gradle 캐시를 `C:\gradle_home`으로 자동으로 옮긴다) |

```powershell
git clone https://github.com/hmy7788/SmartFactory_Vision_Project2.git
cd SmartFactory_Vision_Project2
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 1. 모델·카메라 없이 확인

판정 코어와 테스트는 외부 패키지 없이도 돈다.

```powershell
python -m pytest tests -q                                   # 전체 테스트
python -m scripts.replay_detections --demo --recipe recipe_1  # 합성 시나리오: 부족 → 초과 → 조립 → PASS → H5 NG → 수정 → Mother 유실/복귀
python -m web.server                                        # 웹 화면 합성 데모 → http://localhost:8000
```

## 2. 작업자 화면 (웹)

| 방법 | 명령 |
|---|---|
| 더블클릭 | `run_ui.cmd` — `weights/`의 가중치·카메라를 고르면 브라우저가 열린다. `.pt`/영상 파일을 끌어다 놓아도 된다 |
| 직접 | `python -m scripts.run_ui weights/rtdetr_best.pt` |
| 녹화 영상으로 | `python -m scripts.run_ui weights/rtdetr_best.pt 조립영상.mp4` |
| 모델 교체 | `python -m web.server --source camera --model-type yolo-obb --weights weights/yolo_obb_parts.pt` (`rtdetr` / `yolo` / `yolo-obb` / `rule_based`) |

시연 전 체크리스트(클래스 이름·ROI 보정·confidence·frame gap)는 [docs/web.md](web.md).

## 3. MES 연동 시연

`run_mes_demo.cmd` 더블클릭 → MQTT 브로커(1883) · MES 서버(`http://localhost:8080`, 첫 실행은 jar 빌드 1~2분) · 검사대 화면(`http://127.0.0.1:8000`)이 뜬다.

1. MES 콘솔에서 작업지시(레시피 × 수량)를 발행한다
2. 검사대가 받아서 재료 확인 → 조립 검사를 진행한다. 카메라는 10초 안에 안 고르면 USB 웹캠(가장 큰 번호)으로 자동 선택
3. [작업 완료]마다 결과가 MES로 올라가고, 수량을 채우면 다음 작업지시가 자동으로 내려온다. 완성품을 작업대에서 치워야 다음 재료 확인이 시작된다

따로 띄우려면 `mes/run_broker.cmd` → `mes/run_mes_light.cmd` → `run_station_mes.cmd`. MES 테스트는 `mes/test_mes.cmd`.
Python 쪽에는 `pip install "paho-mqtt>=2.0"`이 필요하다. 메시지 규약: [mes/docs/mes_mqtt.md](../mes/docs/mes_mqtt.md), 서버: [mes/README.md](../mes/README.md).

## 4. CLI 라이브 검사 (OpenCV 창)

```powershell
python -m scripts.live_inspection --camera 1 --recipe 1                                  # RT-DETR (기본)
python -m scripts.live_inspection --model-type yolo-obb --camera 1 --recipe 3
python -m scripts.live_inspection --model-type rule_based --camera 1 --recipe 2          # 학습 모델 없이 classical CV
python -m scripts.live_inspection --video 조립영상.mp4 --save-video outputs/demo.mp4 --no-window
```

키: `[1/2/3]` 레시피 선택 · `[n]` 새 제품 · `[q]` 종료. 카메라가 뒤집혀 나오면 `--flip-horizontal`/`--flip-vertical`. 자세한 옵션은 [docs/live-inspection-usage.md](live-inspection-usage.md).

## 5. 영상 기반 공정 평가

같은 영상을 모델별로 돌려 프레임별 판정을 남기고, 초 단위 정답과 비교한다.

```powershell
python -m scripts.live_inspection --video eval_vid.mp4 --recipe 1 --model-type yolo-obb --weights weights/yolo26_obb_parts_50.pt --device cpu --no-window --eval-log outputs/eval/obb_run03
python -m scripts.evaluate_video --annotation evaluation/annotations/eval_vid.json --run outputs/eval/obb_run03 --output outputs/eval/obb_run03_report
```

채점 규칙: [docs/video-evaluation.md](video-evaluation.md) · 결과: [docs/comparison_run03_05_06_ko.md](comparison_run03_05_06_ko.md)

## 6. 모델 학습·평가

| 모델 | 명령 | 문서 |
|---|---|---|
| YOLO11n-OBB | `run_train_obb.cmd` 더블클릭, 또는 `python -m src.detection.yolo11.prepare_obb_dataset --labels <라벨> --images <사진>` → `python -m src.detection.yolo11.train_yolo_obb` | [docs/detection_obb.md](detection_obb.md) |
| YOLO-OBB 평가 | `python -m src.detection.yolo11.evaluate_obb --weights weights/yolo_obb_parts.pt` (mAP · 긴 변 각도 오차 · CPU 속도) | 〃 |
| RT-DETR-L | `python src/detection/rt-detr/train_rtdetr.py --data <data.yaml> --epochs 10` | [docs/rt-detr-experiment.md](rt-detr-experiment.md) |
| 완성체 분류 (ResNet-18) | `python -m src.classification.train --data <aabb 폴더> --out weights/classifier_resnet18.pt` | [docs/classification.md](classification.md) |

학습이 끝나면 최종 가중치는 자동으로 `weights/`에 복사되고, 학습 로그·plot은 `runs/`, 발표용 리포트는 `reports/`에 남는다.
YOLO26n-OBB는 같은 학습 스크립트에서 `--model yolo26n-obb.pt --out weights/yolo26_obb_parts.pt`로 베이스만 바꿔 학습한다.

받은 가중치가 시스템에 맞는지는 카메라 없이 확인할 수 있다:

```powershell
python -m scripts.check_weights weights/yolo_obb_parts.pt
python -m scripts.check_weights weights/rtdetr_best.pt --model-type rtdetr
```

## 7. 룰베이스·샘플 검증 도구

```powershell
python -m scripts.visualize_rois --preview-outside-angle        # scripts/sample_img 사진에 Mother/Hole/Bolt/Part ROI 표시
python -m scripts.verify_materials --recipe all                 # 재료 사진 수량 검사 (--output 으로 저장 위치 지정)
python src/rule_based/live_hole_check.py --camera 0              # 완성 조립체 Model A/B/C 룰베이스 분류 (웹캠)
```

결과는 `outputs/`의 실행 시각 폴더에 PNG/JSON으로 저장된다. 정지 사진의 READY는 재료 후보일 뿐 1초 안정화·자동 전환 검증이 아니다.
