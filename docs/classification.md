# 완성 조립체 분류 (딥러닝 트랙)

완성된 조립체 사진 한 장 → **model_a / model_b / model_c** (= recipe_1 / 2 / 3). 룰베이스(구멍 개수 세기)와
대조하는 이중 검증용이다. 디텍션(YOLO-OBB) 트랙과는 코드도 데이터도 별개다.

| | 디텍션 (YOLO-OBB) | **분류 (이 문서)** | 룰베이스 (OpenCV) |
|---|---|---|---|
| 입력 | 조립 중 매 프레임 | 조립 끝난 사진 1장 | 조립 끝난 사진 1장 |
| 출력 | 부품 5종의 위치·종류 | 사양 이름 + 확신도 | 막대별 구멍 개수 + "어디가 틀렸나" 텍스트 |
| 코드 | `src/vision`, 코어 | `src/classification` | `src/rule_based` (미구현) |

## 데이터

`aabb/images/{train,test}/model_<x>_NNN.png` — 파일명 앞부분이 클래스다. 부품 사진(bolt_…, part_…)은 무시한다.

| 클래스 | 레시피 | 모양 | train | test |
|---|---|---|---|---|
| model_a | recipe_1 | H1 노랑볼트+2구, H4 주황볼트+3구 | 17 | 3 |
| model_b | recipe_2 | H1·H3 노랑볼트+2구 두 개 | 34 | 6 |
| model_c | recipe_3 | H2 주황볼트+3구 하나 | 34 | 6 |

사진은 1280×720, 배경 검정/회색 두 세션. model_b/c 에는 아무 각도로 놓인 사진이 20장씩 있지만
**model_a 는 전부 똑바로 놓인 사진뿐** — 그래서 회전 증강이 필요하다 (아래).

## 실행

```
run_train_classifier.cmd                    ← 더블클릭. smoke → 학습 → 평가 순서로 돈다
run_train_classifier.cmd D:\other\aabb      ← 사진 폴더가 다른 곳이면
```

수동으로:

```
python -m src.classification.train    --smoke                                            # 파이프라인만 20초 확인
python -m src.classification.train    --data ..\aabb --out weights\classifier_resnet18.pt  # 학습 (CPU 5~10분)
python -m src.classification.evaluate --weights weights\classifier_resnet18.pt --data ..\aabb --gradcam 6
python -m src.classification.predict  --weights weights\classifier_resnet18.pt 사진1.png 사진2.png
python -m src.classification.train    --data ..\aabb --cv 5                              # 5-fold 로 정확도 분산 (15장 test 만으론 한 장이 6.7%p)
python -m src.classification.train    --data ..\aabb --arch convnext_tiny --out weights\classifier_convnext.pt   # 비교 모델
```

결과는 `reports/classification/` — `report.md`(발표용 표), `confusion.png`, `gradcam/*.jpg`, `history.json`, `train_log.txt`.

코드에서:

```python
from src.classification import Classifier
clf = Classifier.load("weights/classifier_resnet18.pt")
r = clf.predict(frame_bgr)        # OpenCV 프레임 / PIL / 경로
r.label        # "model_b"
r.recipe_id    # "recipe_2"
r.confidence   # 0.97
r.unknown      # confidence < 0.6 이면 True — 미완성체를 넣어도 softmax 는 답을 찍기 때문에 둔 안전장치
r.matches("recipe_2")   # unknown 이면 항상 False
```

## 어떻게 학습하나

- **ResNet-18, ImageNet 사전학습** (`config/classification.json` 의 `arch`). 클래스당 20~40장이라 전이학습이 아니면 안 된다.
- **두 단계**: 5 epoch 은 백본 동결·분류 층만(LR 1e-3) → 20 epoch 은 전체(백본 1e-4, 헤드 1e-3, cosine).
  백본을 처음부터 큰 LR 로 풀면 사전학습 특징이 망가진다.
- **epoch 고정, early stopping 없음.** test 로 멈출 시점을 고르면 test 가 검증셋이 된다 (CLAUDE.md: Val 없이 Train/Test).
  test 정확도는 epoch 마다 찍지만 기록일 뿐이다.
- **클래스 가중치** (model_a 17장 vs 34장) + label smoothing 0.05.
- **입력 448×448 letterbox** (16:9 를 비율 유지한 채 정사각형에 넣고 검정으로 채움). 비율을 바꾸면 막대 길이 단서가 사진마다 달라진다.

### 증강 — 촬영 조건에서 나온 것만

| 증강 | 쓰나 | 이유 |
|---|---|---|
| 회전 ±180° | O | 완성체는 아무 각도로 놓인다. model_a 엔 회전 사진이 없어 증강으로 채운다. 안 넣으면 "기울어짐 = a 가 아님" 을 외울 수 있다 |
| 이동 ±8% | O | 놓는 자리가 매번 다르다 |
| 밝기·대비·채도 | O | 두 세션의 조명이 다르다 |
| **좌우 반전** | **X** | 거울상은 다른 사양이다 — H2 에 붙은 3구를 뒤집으면 H4 에 붙은 3구가 된다 |
| **크기 흔들기 (RandomResizedCrop)** | **X** | 카메라 높이가 고정이라 "막대가 길다" 가 그대로 단서다. AI 가 짜주는 학습 코드의 기본값이 이거라서 특히 조심 |

## 숫자를 읽는 법

- test 15장은 한 장이 6.7%p 다. 93.3% 와 100% 는 "한 장 차이". 발표에 낼 땐 `--cv 5` 결과(평균 ± 표준편차)를 같이 두는 편이 정직하다.
- 같은 세션(같은 조명·배경)에서 찍은 사진이 train/test 양쪽에 있으므로, 이 정확도는 "같은 환경" 기준이다. 발표장 조명이 다르면 떨어질 수 있다 → 시연 전에 그 자리에서 몇 장 찍어 `predict` 로 확인.
- `unknown` 이 자주 뜨면 임계값(0.6)을 낮추기 전에 Grad-CAM 을 먼저 본다. 배경에 열이 모이면 임계값 문제가 아니라 모델이 배경을 본 것이다.

## 런타임에서 이런 게 나오면

| 증상 | 먼저 볼 곳 |
|---|---|
| 정확도가 0.33 근처에서 안 움직임 | 클래스 인덱스(체크포인트 `classes` 순서), LR, 정규화 mean/std |
| train 1.00 / test 0.6 | 과적합 또는 증강이 단서를 지움 → 회전·이동만 남기고 다시 |
| 같은 사진인데 실행마다 답이 바뀜 | `model.eval()` 누락 (Classifier 는 load 때 eval 로 둔다) |
| `size mismatch for fc.weight` | 저장할 때와 클래스 수가 다름 — 체크포인트와 데이터 폴더가 짝이 맞는지 |
| 전부 한 클래스로만 나옴 | 클래스 가중치가 빠졌거나 loss 가 안 내려감 → `history.json` 의 train_loss 확인 |
| `Expected more than 1 value per channel` | 마지막 배치가 1장 (train.py 가 그 경우 버리지만 `--batch` 를 바꿨다면 확인) |

## 웹 UI 에 붙이려면 (아직 안 붙임)

`[작업 완료]` 버튼을 누를 때 마지막 프레임을 `Classifier.predict` 에 넣고, 선택한 레시피와 `matches()` 결과를 이력 DB 에
한 컬럼(`classifier_recipe`, `classifier_conf`)으로 남기면 된다. 코어(판정 상태머신)는 건드릴 필요가 없다.
