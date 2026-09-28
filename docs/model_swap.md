# 다른 모델로 UI 돌려 보기

같은 작업자 화면·같은 판정 코어에 **검출 가중치만 바꿔 끼워** 돌려 본다. 학습한 모델끼리 실물 조립 앞에서 비교하는 용도.

## 1. 준비 (처음 한 번)

```powershell
git clone --branch yuseong/ui-demo --single-branch https://github.com/hmy7788/SmartFactory_Vision_Project2.git
cd SmartFactory_Vision_Project2
```

윈도우는 `run_ui.cmd` 를 처음 실행할 때 필요한 패키지(ultralytics · CPU torch · opencv · fastapi · uvicorn)를 알아서 설치한다.
직접 설치하려면 `pip install ultralytics opencv-python numpy fastapi "uvicorn[standard]"`.
GPU 로 돌리려면 `install_torch_gpu.cmd` (CUDA 버전에 맞는 torch 를 고른다).

## 2. 가중치 넣고 실행

1. 가중치(.pt)를 `model/` 폴더에 넣는다. 가중치는 저장소 정책상 Git 에 올리지 않는다 (팀 드라이브·카톡으로 주고받기).
2. 실행

| 방법 | 동작 |
|---|---|
| `run_ui.cmd` 더블클릭 | `model/*.pt` 목록에서 번호 선택 → 카메라 번호 선택 → 브라우저 자동 |
| `.pt` 를 `run_ui.cmd` 위에 끌어다 놓기 | 그 모델 + 웹캠 |
| `.pt` 와 영상(.mp4 등)을 같이 끌어다 놓기 | 웹캠 대신 녹화 영상으로 같은 판정 |
| `python -m scripts.run_ui model/내모델.pt` | 맥·리눅스·터미널. `--camera 1`, 영상 경로, `--demo` 도 받는다 |

추가 옵션은 그대로 `web.server` 로 넘어간다: `--imgsz 480`(CPU 가 느릴 때) · `--conf 0.3` · `--port 8001` · `--recipe recipe_2`.

어떤 모델로 돌고 있는지는 사이드바 맨 아래(버전 밑)와 **진단 탭 → 모델** 줄에 나온다. 추론 시간은 진단 탭 "모델 추론 / 판정 지연".

## 3. 넣을 수 있는 모델

| 모델 | 되는가 | 메모 |
|---|---|---|
| YOLO-OBB (yolov8/11/26 …-obb) | O | 회전 박스 — 각도까지 나온다. 지금 시연 모델 (`yolo_obb_parts.pt` = YOLO11n-OBB) |
| YOLO detect (AABB) | O | 각도가 없어서 OpenCV 각도 보정을 자동으로 켠다 (`--no-refine-angles` 로 끔) |
| RT-DETR | O | 자동 판별해서 `ultralytics.RTDETR` 로 연다 (YOLO 로 열면 박스가 틀린다). CPU 에선 느리다 — 화면은 안 끊기고 판정만 늦게 갱신 |
| segment · classify · pose | X | task 가 obb/detect 가 아니면 실행 전에 멈춘다 |

판별은 `src/vision/model_loader.py` 한 곳에서 한다. 자동 판별이 틀리면 `--model-type yolo|rtdetr` 로 강제.
YOLO26 가중치는 ultralytics 8.4 이상이 필요하다 (`pip install -U ultralytics`).

먼저 파일만 확인하려면: `python -m scripts.check_weights model/내모델.pt` — 종류·task·클래스 매핑·샘플 사진 한 장 추론 결과를 보여 준다.

## 4. 클래스 이름 맞추기

코어가 아는 이름은 5개: `bolt_1`(노랑·짧은 볼트) · `bolt_2`(주황·긴 볼트) · `mother_part`(5구) · `part_3hole` · `part_2hole`.

- 모델이 이 이름 그대로 내면 할 일 없음.
- 한글 이름(`볼트_주황` 등)은 `config/class_mapping.json` 이 이미 연결한다.
- 다른 이름이면 **가중치 옆에 `<가중치이름>.classes.json`** 을 만든다 — 그 모델에만 적용되고 공용 매핑은 안 건드린다.

예: `model/내모델.pt` 옆에 `model/내모델.classes.json`

```json
{
  "orange_bolt": "bolt_2",
  "yellow_bolt": "bolt_1",
  "bar_5": "mother_part",
  "bar_3": "part_3hole",
  "bar_2": "part_2hole",
  "hand": null
}
```

`null` 은 그 클래스를 버린다 (손·조립체처럼 이 시스템이 안 쓰는 클래스). 매핑 안 된 이름이 있으면 화면을 띄우기 전에 어떤 이름이 문제인지 알려 주고 멈춘다
— 그대로 띄우면 그 부품이 잡히는 프레임마다 판정이 보류가 되기 때문. 5개 중 모델이 못 내는 부품은 경고만 한다 (그 부품이 필요한 레시피는 PASS 가 안 나옴).

## 5. 비교할 때 맞춰 둘 것

- 같은 카메라·조명·배경(검은 판)·해상도(`--camera-size 1280x720` 기본).
- `--imgsz` 는 학습 때 값(보통 640)이 기준. CPU 가 느려 480 으로 낮추면 작은 볼트 인식이 떨어질 수 있다.
- 판정 임계(0.5)·안정화 시간은 `config/mvp.json` — 모델만 비교하려면 건드리지 않는다.
- 이력·분석 탭 기록은 `data/pokayoke.db` 에 모델 파일 이름과 같이 남는다 (runs.model_file). 모델별로 따로 보려면 `--db data/내모델.db`.
