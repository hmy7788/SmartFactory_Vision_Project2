# 부품 검출 (YOLO-OBB 트랙)

카메라 프레임 → **부품 5종의 종류·위치·각도**. 코어(`src/geometry`, `src/process`)가 이 결과를 Mother 기준 자리(H1~H5)로
바꿔 레시피와 대조한다. 판정은 코어가 하고, 모델은 "무엇이 어디, 몇 도" 만 답한다.

| | AABB 모델 (지금까지) | **OBB 모델 (이 문서)** |
|---|---|---|
| 박스 | 회전 없는 직사각형 | 회전 사각형 — 각도가 같이 나온다 |
| 기울어진 부품 | `--refine-angles` 로 OpenCV 가 각도를 되살림 (사진 100장 중 82장) | 모델이 직접 각도를 냄 |
| 코어 연결 | `src/vision/detection_adapter.py` 가 각도 0 으로 받음 | 같은 어댑터가 `result.obb.xywhr` 를 그대로 받음 |
| 코드 | `src/vision/angle_refiner.py` | `src/detection/` |

## 실행

```
run_train_obb.cmd                                        ← 더블클릭. 데이터셋 폴더 → 학습 → test 평가 → 속도 측정
run_train_obb.cmd ..\labels-20260926T031248Z-1-001 ..\aabb\images 150     ← 라벨 폴더, 사진 폴더, epoch 을 직접
```

수동으로:

```
python -m src.detection.yolo11.prepare_obb_dataset --labels ..\labels-20260926T031248Z-1-001 --images ..\aabb\images
python -m src.detection.yolo11.train_yolo_obb                                  # 100 epoch, GPU 자동, 끝나면 평가까지
python -m src.detection.yolo11.evaluate_obb                                    # 가중치만 다시 평가 (mAP·각도·속도)
python -m src.detection.yolo11.evaluate_obb --bench-only                       # 시연 노트북에서 속도만
python -m src.detection.yolo11.realtime_inference --source 0 --imgsz 480       # 모델만 눈으로
run_ui.cmd  /  run_live.cmd                                             # 웹 화면 — weights\yolo_obb_parts.pt 를 읽는다
```

결과는 `weights/yolo_obb_parts.pt` (코어·웹이 읽는 자리) 와 `reports/detection_obb/`
— `report.md` (발표 슬라이드 04·05 에 그대로 넣는 표), `metrics.json`, `train_log.txt`, `results.csv`, `test_val_batch0_pred.jpg`.

## 데이터

- 라벨: 구글 드라이브 `labels-…/train|test/*.txt` (980장 = train 831 / test 149). YOLO-OBB 형식 `class x1 y1 … x4 y4`.
- 사진: 같은 이름의 `.jpg/.png` — AABB 데이터셋 `aabb/images/train|test` 와 이름이 같다 (같은 로보플로우 프로젝트에서 나온 두 가지 라벨).
- 클래스 번호는 팀 규약 그대로: 0 볼트_주황=**bolt_2**, 1 볼트_노랑=**bolt_1**, 2 나무_5구멍=**mother_part**, 3 나무_3구멍=**part_3hole**, 4 나무_2구멍=**part_2hole**.
  data.yaml 에는 영문 이름을 쓴다 — 코어 이름과 같아 `class_mapping.json` 없이 바로 통하고, ultralytics 결과 그림(cv2)이 한글을 못 그려 `???` 로 나오는 것도 피한다.

**라벨의 절반은 진짜 회전 박스가 아니다.** 낱개 부품 사진(`bolt_*`, `part_*`, `mother_part_*`)은 `auto_label_iconic.py` 가 `minAreaRect` 로
만든 회전 박스지만, 로보플로우에서 손으로 그린 프레임(조립 과정·픽킹·완성체 `model_*`)은 회전 없는 직사각형을 OBB 형식으로 적은 것이다.
`prepare_obb_dataset` 가 split 별 "회전 라벨 비율" 을 `dataset_report.md` 에 적는다. 결과:

- 학습은 된다 (직사각형도 OBB 의 한 경우). 다만 기울어진 부품이 헐거운 직사각형으로 라벨된 사진이 섞여 있어 각도 학습이 조금 흐려진다.
- **각도 정확도는 회전 라벨이 있는 사진으로만 잰다** (`evaluate_obb` 의 "회전 라벨 n" 열). 직사각형 라벨은 부품이 기울어져 있어도 0° 라서 오차가 과장된다.
- 여유가 있으면 로보플로우에서 `model_*` 완성체 사진만이라도 회전 박스로 다시 그리는 게 가장 싸게 각도 성능을 올리는 길이다.

### val 을 떼는 이유

팀 방침은 "val 없이 train/test" 다. RT-DETR 은 ultralytics 설정상 test 를 val 자리에 넣었고, 그래서 best.pt 를 test 점수로 골라
지표가 낙관적일 수 있다고 발표자료에 적었다. 여기서는 **train 에서 묶음(bolt/part/model_a/recipe1_process …)별로 10% 를 떼어 val 로 쓰고
test 149장은 학습·선택 어디에도 쓰지 않는다.** CLAUDE.md 의 단서("YOLO 가 학습 옵션으로 train 일부를 val 로 떼는 건 방침과 상충하지 않음")에
맞는 방식이다. RT-DETR 과 완전히 같은 조건으로 비교하고 싶으면 `--val-frac 0`.

## 팀원 스크립트에서 바꾼 것과 이유

| | 받은 스크립트 | 바꾼 것 | 이유 |
|---|---|---|---|
| 폴더 | `data/iconic/{클래스}/` 를 기대 | 드라이브 `labels-…/train,test` + `aabb/images` 를 그대로 읽음. 사진 폴더는 근처에서 자동 탐색 | 실제 데이터는 이미 train/test 로 나뉜 로보플로우 export 다 |
| 분할 | 70/15/15 새로 나눔 | test 149 고정, val 만 train 에서 뗌 | test 가 바뀌면 RT-DETR 과 비교가 안 된다 |
| 라벨 검사 | 없음 | 9칸·클래스 범위·좌표 범위·넓이 0·사진 없는 라벨·회전 비율 보고 | 조용히 빠지는 사진이 없게 |
| epochs / patience | 5 / 20 | 100 / 30 | patience 가 epochs 보다 크면 조기 종료가 없는 것과 같다 |
| 재현성 | seed 없음 | `seed=0, deterministic=True`, 설정을 `train_meta.json` 에 기록 | 발표 수치는 다시 돌려도 같아야 한다 |
| 장치 | `device="0"` 고정 | auto (GPU 없으면 CPU, CPU 면 batch 8) | 시연 노트북에서도 돌아가게 |
| workers | 기본 8 | 윈도우는 2~4 | 윈도우 DataLoader 는 프로세스가 많으면 오히려 느리거나 멈춘다 |
| copy_paste | 0.2 | 0 | OBB 폴리곤을 뒤집어 붙이는 증강 — 결과 그림이 어색하고 이득이 불분명 |
| mosaic | 0.3 | 0.5 + close_mosaic 10 | 낱개 사진을 붙여 조립 장면(여러 부품)을 만든다. 마지막 10 epoch 은 실제 분포로 |
| scale | 기본 0.5 | 0.2 | 카메라 높이가 고정이라 크기가 단서다 (2구 vs 3구 길이) |
| 평가 | mAP 만 | mAP + 클래스별 + **각도 오차** + **CPU 속도**, 발표 표 형태로 `report.md` | 코어가 쓰는 건 박스가 아니라 각도고, 시연은 CPU 다 |
| 실시간 뷰어 | 한글 라벨(cv2 는 `???`), 웹캠 2번 기본, MJPEG 주장(구현 없음) | 영문 라벨 + 긴 변 방향·각도 표시, 웹캠 0번, `--skip N` | 각도가 맞는지 눈으로 확인하는 용도로 한정 |
| 가중치 자리 | `checkpoints/yolo_obb_parts.pt` | `weights/yolo_obb_parts.pt` | 코어·웹·`check_weights.py` 가 읽는 자리 |

그대로 둔 것: `degrees=180` (OBB 의 존재 이유), `hsv_h=0.01` (노랑/주황은 색으로 가른다 — 색조를 흔들면 정답이 바뀐다), `fliplr=0.5`
(디텍터는 좌우 판정을 안 하므로 안전 — 분류기와 다르다), `flipud=0`.

## 발표자료에 적는 법

`reports/detection_obb/report.md` 의 첫 표가 04. 디텍션 모델 슬라이드의 "최종 모델" 열이고, 둘째 표가 05. 디텍션 결과 슬라이드의
클래스별 막대다. RT-DETR·AABB 값은 참고로 같은 표에 넣어 두었다 (AABB 는 회전 없는 IoU, OBB 는 회전 IoU 라 잣대가 조금 다르다 — 각주로).
"노트북 CPU" 칸은 **시연 노트북에서** `python -m src.detection.yolo11.evaluate_obb --bench-only` 로 잰 값을 쓴다 (학습 PC 값이 아니라).

## 판단·의심·디버깅 포인트

**내가 내리는 판단**
- OBB 로 갈지 AABB+각도 보정으로 남을지: `report.md` 의 각도 오차(회전 라벨 기준)가 코어 허용치(Mother ±15°)에 넉넉히 들어오고,
  mAP50 이 AABB 모델과 비슷하면 OBB 로 간다. 각도가 10° 를 자주 넘기면 라벨(직사각형 섞임) 문제부터 본다.
- 모델 크기(n/s): 시연은 CPU 라 `n` 이 기본. `cpu_480` 이 100 ms 를 넘으면 `s` 는 고려 대상이 아니다.
- epoch: `results.csv` 에서 val mAP 가 마지막 30 epoch 동안 평평하면 충분. best 가 마지막 5 epoch 안이면 `--epochs` 를 늘려 본다.

**AI 가 짜 준 코드에서 의심할 곳**
- 클래스 번호 ↔ 이름 순서. 한 칸 밀리면 mAP 는 높게 나오는데 화면에선 노랑이 주황으로 찍힌다. `data.yaml` 의 `names` 와
  `config/class_mapping.json` 오른쪽을 같이 본다. `check_weights.py` 로 `model.names` 를 확인.
- val 이 test 와 같은 사진인지 (`splits.json` 의 val ∩ test 가 비어야 한다).
- 증강 중 색을 건드리는 값 (`hsv_h`). 볼트 색 구분이 무너지면 여기부터.
- 각도 규약: ultralytics `xywhr` 의 `r` 은 라디안, (w,h) 가 바뀌어 나올 수 있다. 긴 변으로 접는 `long_axis_angle` 을 거치지 않고
  `r` 을 바로 쓰면 90° 가 뒤집힌다 (코어 `major_axis` 와 같은 규약을 쓴다).

**터졌을 때 어디를 보나**
- `ignoring corrupt image/label` 이 여러 장 → 라벨 좌표가 1 을 넘거나 칸 수가 틀림. `dataset_report.md` 의 "라벨 검사" 절.
- `CUDA out of memory` → `--batch 8`, 또는 `--imgsz 480`.
- 학습이 첫 epoch 에서 멈춰 있음(윈도우) → `--workers 0`.
- `AMP checks failed` 경고 → 인터넷 없이 yolo11n.pt 를 못 받은 것. `--set amp=False` 로 우회 (조금 느려질 뿐).
- mAP 는 좋은데 웹 화면에서 못 잡음 → 웹 `conf`(0.25)·`imgsz`(480) 와 평가 조건이 다름. `realtime_inference --imgsz 480` 로 같은 조건에서 본다.
- 각도가 90° 씩 틀림 → 어댑터가 `xywhr` 를 그대로 넘기는지, 코어의 `major_axis` 가 (w,h) 를 바꾸는지 확인.

**면접에서 물어볼 만한 것**
- 왜 OBB 인가: 부품이 아무 각도로 놓이는데 회전 없는 박스는 배경을 많이 포함하고, 코어는 Mother 의 각도가 있어야 H1~H5 를 계산한다.
- mAP 가 높은데 왜 각도 오차를 따로 재나: 코어가 쓰는 건 박스가 아니라 긴 변 방향이고, mAP 는 회전 IoU 0.5 만 넘으면 각도가 10° 틀려도 맞다고 친다.
- val 을 왜 떼나 / test 를 val 로 쓰면 무엇이 낙관적이 되나: best.pt 를 test 로 고르는 순간 test 는 더 이상 '한 번도 안 본 데이터' 가 아니다.
- 라벨의 절반이 직사각형인 데이터로 각도를 배울 수 있나: 배운다, 다만 그 사진에선 각도 손실이 잘못된 정답을 향한다 — 회전 라벨만으로 각도를 평가하는 이유.
