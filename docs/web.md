# 웹 UI (web/)

작업자 화면 + 이력·분석·진단 탭. 카메라·모델 없이도 돈다 (합성 데모). 코어(`src/`)는 건드리지 않는다.

## 실행

```bash
pip install -r requirements.txt          # fastapi(→ starlette) + uvicorn[standard](→ websockets) 가 들어 있다
python -m web.server                     # 합성 데모, http://localhost:8000
python -m web.server --speed 2           # 데모 시나리오 2배속 (발표 리허설)
python -m web.server --source jsonl --jsonl detections.jsonl     # 기록한 검출 재생
python -m web.server --source camera     # 웹캠 + RT-DETR(기본, runs/rtdetr/full_run/weights/best.pt)
python -m web.server --source camera --model-type yolo-obb --weights model/내모델.pt   # --model-type 아래 참고
python -m scripts.run_ui                 # 가중치·카메라를 골라서 띄우는 실행기 (윈도우: run_ui.cmd)
python -m web.server --video 조립영상.mp4  # 녹화 영상으로 같은 판정. 끝나면 마지막 장면 유지(--video-end hold, 기본) · loop · stop
python -m unittest tests.test_web        # 13개, 약 20초
```

DB 는 `data/pokayoke.db` 에 생긴다 (`--db` 로 바꿈). 저장 규칙은 [storage.md](storage.md).

## 구조

```
소스(web/source.py) ──DetectionFrame──▶ 파이프라인(web/pipeline.py) ──payload(JSON)──▶ 서버(web/server.py) ──WS/REST──▶ 화면(web/static/)
                                              │ service.update()                         │
                                              └── Store.record() (web/store.py)          └── MJPEG /video (소스가 JPEG 를 줄 때만)
```

| 파일 | 하는 일 |
|---|---|
| `web/source.py` | `DemoSource`(합성 시나리오) · `JsonlSource`(기록 재생) · `CameraSource`(웹캠+YOLO, 가중치만 있으면 됨). 셋 다 `frames()` 가 `(DetectionFrame, JPEG|None)` 을 낸다 |
| `web/pipeline.py` | 프레임마다 코어 `update()` → Store 기록 → payload 생성. 버튼 명령(레시피 선택·새 작업·작업 완료)은 프레임 사이에 처리 |
| `web/server.py` | Starlette 앱. `/ws` 로 payload 를 밀고, `/api/*` 로 Store 를 읽는다 |
| `web/static/` | `index.html` 껍데기, `app.js` 화면 전부(해시 라우팅 SPA), `app.css` |

파이프라인은 자기 스레드에서 돌고, 서버는 마지막 payload 를 들고 있다가 새 접속과 `/api/state` 에 바로 준다.

## 화면

| 탭 | 대상 | 내용 |
|---|---|---|
| 작업 | 작업자 | 영상+오버레이(맞음/틀림/아직/비움), 재료 표, 자리별 표, 큰 판정 카드. 확률·클래스 코드 없음. PASS 확정 때만 **작업 완료** 버튼 → 기록 후 `reset()`. NG 는 치우면 자동 해제(버튼 없음). 보류(HOLD) 는 보이지 않는다 — 진단 탭에서만 (0927c) |
| 레시피 | 작업자·리더 | 레시피별 정답 자리·부품 그림과 재료 수량 |
| 이력 | 리더 | 제품별 결과(COMPLETED/ABANDONED, 사이클, NG·HOLD 횟수, 일발통과)와 타임라인(이벤트 순서) |
| 분석 | 리더·품질 | FPY(전체·일별), 사이클타임 분포(재료/조립), 오류 파레토(조립·재료), 자리×오류 히트맵, NG 복구 시간 |
| 진단 | 개발자 | 실시간: 코어 후보/확정, 안정화, issue 코드 원문, 검출 confidence, ROI 폴리곤, 각도. 시스템: HOLD 사유, confidence 분포, 프레임 지연·gap 시계열, 현재 config |

대표 오류(작업 화면의 큰 글씨) 선정: `WRONG_*` > `UNEXPECTED_COMPONENT`/`EXTRA_COMPONENT` > `PART_ORIENTATION_ERROR` > `MISSING_*`, 같은 급이면 낮은 H 번호. 나머지는 "외 N건". 코드는 `app.js` 의 `PRIORITY`/`primaryIssue`.

### 작업 화면이 흔들리지 않게 — 2026-09-27

작업 화면은 payload 를 그대로 그리지 않는다. 코어의 **확정(`confirmed`)** 과 화면 쪽 완충값 몇 개로 만든 파생 상태만 그린다
(`app.js` 의 `deriveView()` → `S.shown · S.rings · S.obs · S.matView · S.holdMode · S.chip`). 판정 자체는 바꾸지 않고, 보여 주는 타이밍만 늦춘다.

| 완충 | 값 | 무엇을 막나 |
|---|---|---|
| `S.shown` 마지막 확정 판정 | — | 후보(`candidate`) 는 프레임마다 바뀐다. 큰 글씨·NG 상세·자리 표는 확정만 쓴다. 코어는 HOLD 가 오면 `confirmed` 를 비우지만 화면은 마지막 확정을 들고 있는다 |
| `MAT_WINDOW_MS` 재료 수량 최빈값 | 700ms | 한두 프레임 오검출·손 가림으로 "있음" 칸과 "N개 더 놓으세요" 가 깜빡이는 것. 코어는 1000ms 안정을 따로 요구하므로 판정엔 영향 없음 |
| 보류(HOLD) 숨김 (0927c) | — | 작업자는 OK/NG 만 본다. 코어가 보류해도 판정 카드·자리 표는 마지막 확정 그대로, "보류/잠깐/확인 중" 같은 말 없음. PASS 중 보류면 [작업 완료] 만 잠근다(서버가 409 를 줄 버튼) |
| `GEOM_KEEP_MS` 링 유지 | 1500ms | 보류 중 영상 위 H 링을 마지막 위치에 유지 (손이 지나갈 때 링이 깜빡이지 않게). 더 길면 Mother 가 움직였을 수 있어 지운다 |
| `HOLD_HINT_MS` 할 일 한 줄 | 3000ms | 작업자가 손으로 고칠 보류(Mother 기울어짐·두 개·안 보임, 카메라 끊김) 가 이만큼 이어지면 판정 카드 맨 아래에 할 일만 한 줄 ("Mother 를 똑바로 놓아 주세요 (지금 26° 기울어짐)"). 손 가림(`AMBIGUOUS_ASSOCIATION`) 은 손을 떼면 풀리므로 안내 없음 |
| 진행 막대 | — | 재료가 딱 맞으면 "준비 완료" + 1000ms 막대. 후보가 바뀌면 코어처럼 처음부터 |

값은 `app.js` 맨 위 `UI` 상수.

**그리는 단위 (0927b)**: 작업 화면은 뼈대(영상 카드) · 헤더 · 자리/재료 표 · 판정 카드 네 조각을 `workKeys()` 의 조각별 키가 바뀔 때만 따로 다시 그린다.
뼈대는 영상 유무·해상도가 바뀔 때만 — 통째로 다시 그리면 `<img src=/video>` 가 새로 열려 영상이 깜빡인다. 막대·각도 숫자는 `updateLive()` 가 제자리에서.

**자리 표 규칙 (0927b)**: 상태(맞음/틀림/아직/비움) 는 `confirmed` 에서만, '지금' 칸 이름은 코어가 `stable` 인 프레임의 `observed` 에서만 찍는다.
0927a 는 `confirmed` 가 매 프레임 실려 온다는 점을 놓쳐 '지금' 칸을 매 프레임 원시 `observed` 로 다시 만들었다 → 표가 계속 깜빡였다 (`tests/test_web_ui.js` 의 "hole table ignores per-frame observed jitter" 가 이걸 잡는다).
조립 시작 직후 확정 전에는 후보를 쓰지 않고 '전부 아직', 보류 중엔 마지막 확인 상태 그대로.

**표 색 (0927c)**: 채운 줄 = 결과 (초록 ✓ 맞음 · 빨강 ✕ 틀림), 흰 줄 = 아직 할 것(파란 글씨) · 비움(회색). 조립이 진행될수록 표가 초록으로 찬다. 재료 표도 같은 규칙.

**캐시 (0927b)**: `/` 와 `/static/*` 는 `Cache-Control: no-cache` (`NoCacheStatic`) — 파일을 바꿨는데 F5 로 옛 화면이 뜨던 문제. 사이드바 맨 아래 `화면 0927c` 같은 표시로 지금 뜬 화면 버전을 확인한다 (`app.js` 의 `UI_VERSION`).
검사: `node tests/test_web_ui.js` (또는 `python -m unittest tests.test_web` 의 `UiLogicTests`) — 흔들리는 payload 순서를 넣고 화면이 몇 번 다시 그려지는지 센다.

의심 지점: (1) 확정이 오래 안 되면(손이 계속 들어와 있음) 옛 판정이 "확인 중" 칩과 함께 남는다 — 코어 `status` 와 같은 성질. (2) 재료 최빈값은 부품을 새로 놓은 뒤 ~350ms 늦게 반영된다. (3) `ts_ms` 기준이라 폴링 폴백(200ms) 에서도 같은 값이 유지된다.

## payload 계약 (WS `/ws`, GET `/api/state`)

파이프라인이 프레임마다 만든다. 화면은 이것만 본다.

| 키 | 출처 | 뜻 |
|---|---|---|
| `phase`, `evaluated_phase`, `status`, `stable` | Snapshot | 코어 그대로 (`CHECK_MATERIALS`/`ASSEMBLING`, `READY/IN_PROGRESS/PASS/NG/HOLD`) |
| `candidate{status,issues}`, `confirmed` | Snapshot | 후보(매 프레임) / 확정(안정화 뒤). 작업 화면은 `status`(=확정) 를, 진단은 둘 다 |
| `materials{expected,observed}` | Snapshot | 재료 단계 수량 |
| `observed{H1..H5:{bolt:[],part:[]}}` | Snapshot | 자리별로 붙은 검출 |
| `geometry{pose,holes,bolt_rois,part_rois,part_rois_down}` | Snapshot | Mother-local 기하 (`part_rois` 위쪽, `part_rois_down` 아래쪽 거울). HOLD(각도 초과·Mother 없음) 면 `{}` |
| `detections[]` | 원본 프레임 | 클래스·confidence·OBB. Snapshot 에는 없어서 파이프라인이 보탠다 (진단용) |
| `mother_angle_deg` | 파이프라인 | HOLD 때도 각도를 보여 주려고 `major_axis()` 를 한 번 더 부른다 |
| `events[]` | Store 기록 | 최근 12개 변화 이벤트 (`STATUS_CHANGED`, `ASSEMBLY_STARTED`, …) |
| `timing{gap_ms,total_ms,fps,max_frame_gap_ms,stable_ms,material_stable_ms,max_angle_deg}` | 파이프라인·config | 진단 표시용 |
| `recipe`, `recipes`, `run_id`, `product_id`, `frame_size`, `has_video`, `calibration_status` | | 헤더·오버레이 좌표계·영상 유무 |
| `video_at_end` | 소스 | `--video` 에서 영상이 끝나 마지막 장면을 유지 중 (작업 화면에 안내 칩) |

`frame_size` 는 소스가 정한다 — 오버레이는 이 좌표계를 canvas 에 맞춰 늘린다. 카메라를 붙일 때 실제 캡처 해상도를 넣어야 박스가 맞는다.

## REST

| 경로 | 뜻 |
|---|---|
| `POST /api/recipe/{id}` | 레시피 변경 → 열린 제품 ABANDONED, 코어 reset. 모르는 id 는 404 |
| `POST /api/reset` | 새 작업 (열린 제품 ABANDONED) |
| `POST /api/complete` | 작업 완료. PASS 확정이 아니면 409 `{ok:false, reason}` |
| `GET /api/history?limit&recipe_id&result&ng_only&hold_only` | 제품 목록 |
| `GET /api/timeline/{product_id}` | 그 제품의 이벤트 순서 |
| `GET /api/analytics?days=7` | `fpy, fpy_daily, cycle, pareto, material_pareto, heatmap, recovery` |
| `GET /api/diagnostics?days=7&hours=1` | `hold_reasons, confidence, metrics, config, run_id` |
| `GET /api/recipes`, `GET /api/config` | 레시피 목록 / 현재 config |
| `GET /video` | MJPEG. 소스가 JPEG 를 안 주면(데모·jsonl) 404 → 화면은 합성 부품 그림으로 대체 |

WebSocket 이 안 열리면(`websockets` 미설치 등) 화면이 알아서 200ms 폴링(`/api/state`) 으로 넘어간다. 헤더의 점이 초록이면 WS, 노랑이면 폴링.

## 카메라 붙이기 — 시연 전 체크리스트

`CameraSource` 는 구현돼 있다. 기본(`--model-type rtdetr`)은 `runs/rtdetr/full_run/weights/best.pt`가
있으면 바로 된다. YOLO-OBB 가중치를 쓰려면 `model/yolo_obb_parts.pt`에 두고 `--model-type yolo-obb`
(자세한 선택지는 위 "검출 모델 교체" 참고):

```bash
pip install -r requirements.txt                      # ultralytics, opencv, uvicorn[standard], fastapi
python -m web.server --source camera                 # 카메라 0번, 1280x720, conf 0.25, imgsz 640, rtdetr
python -m web.server --source camera --camera 1 --camera-size 1920x1080 --model-type yolo-obb --weights model/best.pt
```

준비물이 빠지면 서버가 시작할 때 한국어로 알려 주고 멈춘다 (패키지 없음 / 가중치 없음). 30분 뒤에 "왜 보류만 뜨지" 하는 일을 막으려고.

시연 전에 순서대로 확인할 것:

1. **클래스 이름** — 모델이 내는 이름이 `config/class_mapping.json` 의 왼쪽(한글)과 같아야 한다. 다르면 그 검출은 버려지고 프레임이 `input_valid=False` 가 되어 화면이 "보류"에 머문다. 진단 탭 `source` 줄에 `ValueError: Invalid detection identity/class` 가 뜨면 이거다.
2. **ROI 보정** — `config/mvp.json` 의 `hole_alphas`, `bolt_half_*`, `part_rois` 는 실물로 잰 값이 아니다 (`calibration_status: UNVALIDATED_DEFAULTS`). 카메라를 고정한 뒤 진단 탭 → "오버레이 상세"를 켜고, 실제로 꽂은 볼트·파트가 사각형 안에 들어오도록 값을 맞춘다. 이걸 안 하면 맞게 꽂아도 "아직"으로 나온다. 맞추고 나면 `calibration_status` 를 바꿔 둔다.
3. **confidence** — 진단 탭 "클래스별 confidence" 차트에서 정상 검출이 0.5 위에 안정적으로 모이는지. 밑에 걸치면 판정이 깜빡인다. 그때 `--conf` 가 아니라 config 의 `confidence_threshold` 를 조정한다 (후보와 판정 임계는 다른 값).
4. **frame gap** — 진단 탭 `frame gap` 이 250ms 를 자주 넘으면(느린 노트북 CPU) `max_frame_gap_ms` 를 올리거나 `--imgsz 480` 으로 줄인다. 넘을 때마다 HOLD 가 뜬다.
5. **Mother 각도** — 지그가 화면 수평에서 ±15° 안에 있어야 한다. 넘으면 호박색 HOLD.
6. **조명·배경** — 학습 데이터와 같은 검은 배경. 진단 탭에서 오검출(없는 물체가 잡힘)이 보이면 조명부터.

알려진 모델 이슈: 9/22 중간 모델은 3구 파트를 Mother 로 오분류했다 (`docs/validation_2026-09-22.md`). 그러면 `MULTIPLE_MOTHERS` HOLD 가 뜬다. 새 모델에서 이게 해결됐는지가 첫 확인 사항.

`--source jsonl` 로 기록을 재생하면 카메라 없이도 실제 검출로 화면을 확인할 수 있다 (`scripts/replay_detections.py` 와 같은 형식).

## Starlette 로 짠 이유

팀 결정은 FastAPI 였다. 이 환경에서 fastapi 를 설치할 수 없어서(패키지 서버 차단) 그 아래층인 Starlette 로 짰다. FastAPI 는 Starlette 위의 얇은 층이고 `pip install fastapi` 하면 starlette 가 같이 온다 — 그래서 팀 환경에서는 추가 설치 없이 그대로 돈다.

이 서버는 요청 본문 검증이 없어서(POST 는 전부 빈 본문) FastAPI 층이 할 일이 없다. 그래도 FastAPI 로 바꾸고 싶으면 `create_app()` 끝의 `Starlette(routes=[...])` 를 `FastAPI()` + `app.add_api_route(...)`/`app.websocket(...)` 로 바꾸면 되고 핸들러 함수는 그대로다. 약 20줄.

## 데모 배속 (`--speed`)

시나리오 단계 길이만 줄이면 코어의 안정화 창(재료 1000ms, 조립 400ms) 이 끝나기 전에 다음 단계로 넘어가 NG·PASS 가 확정되지 않는다. 그래서 `demo_config()` 가 두 창도 같은 배율로 줄인다 (frame gap 은 그대로). 진단 탭의 `stable_ms` 가 줄어든 값으로 보이는 게 맞다. 실제 소스에는 적용되지 않는다.

## 알려진 한계 / 의심 지점

- **과검율 없음**: 사람이 "이건 실제로 맞았다" 고 표시하는 입력이 없어서 오검(false NG) 을 셀 수 없다. 넣으려면 이력 탭에 "오판정" 버튼과 `products.verdict_override` 컬럼이 필요하다.
- `calibration_status = UNVALIDATED_DEFAULTS`: ROI 가 실물 보정 전이라 데모의 부품 크기(`PART_LEN`) 는 실물 비율로 넣었을 뿐이다. 카메라를 붙이면 `config/mvp.json` 의 ROI 부터 맞춰야 오버레이의 "맞음" 이 맞다.
- 오버레이의 H 라벨·링은 확정(`confirmed`) 에서만 갱신하고 HOLD 유예 중엔 유지한다 (위 "작업 화면이 흔들리지 않게"). 진단 탭은 매 프레임 갱신.
- 헤더(레시피 select) 는 payload 의 모양이 바뀔 때만 다시 그린다 — 매 프레임 그리면 select 를 조작할 수 없다.
- 하드 SVG 차트(외부 라이브러리 없음). 데이터가 수백 제품을 넘으면 `/api/analytics` 의 `days` 를 줄이거나 Store 쿼리에 인덱스를 보태야 한다.
- 브라우저 1개 기준으로 확인했다. 여러 브라우저가 붙으면 `Hub` 가 전부에 fan-out 하지만 부하는 재지 않았다.

## 검출 모델 교체 — `--model-type` (2026-09-28, model_loader/angle_refiner 대체)

`CameraSource`는 이제 자체 `model_loader.py`/`angle_refiner.py` 없이, `scripts/live_inspection.py`와 같은
어댑터(`src/vision/rtdetr_adapter.py`, `src/vision/rule_based_adapter.py`)를 그대로 쓴다.
`--model-type`으로 고른다 (기본 `rtdetr`):

| 값 | 가중치 | 각도 처리 |
|---|---|---|
| `rtdetr`(기본) | `runs/rtdetr/full_run/weights/best.pt` | AABB만 나와서 어댑터가 mother 각도를 영상에서 복원 |
| `yolo` | `--weights` 필수 | rtdetr와 같은 AABB, 같은 어댑터 |
| `yolo-obb` | `model/yolo_obb_parts.pt` | 결과에 각도가 이미 있어 `detection_adapter.from_ultralytics`로 바로 변환 (한글 클래스명 매핑도 이 경로만 씀) |
| `rule_based` | 불필요 | classical CV(색상+구멍 개수), 모델 자체가 없음 |

```bash
python -m web.server --source camera --camera 1                                   # rtdetr(기본)
python -m web.server --source camera --camera 1 --model-type rule_based            # 모델 없이
python -m web.server --source camera --camera 1 --model-type yolo-obb --weights model/best.pt
```

⚠️ 예전 "부품이 Mother 아래쪽에 오면 H1/H5를 못 가른다"는 코어 레벨 문제(당시 기록: 아래쪽으로 뒤집은
사진 18장 실패)는, `experiment/rt-detr`에서 들여온 코어(`src/geometry/association.py`,
`src/process/evaluator.py`)가 해결했다 — 조립체 전체가 진짜 180도 회전한 경우(구멍 번호와 위/아래가
동시에 뒤집힌 경우)는 `evaluate_symmetric`의 미러 가설이 그대로 인정하고, 부품 하나만 반대쪽에 붙은
진짜 오류는 `PART_WRONG_SIDE`로 NG를 낸다 (`tests/test_relaxed_orientation.py`).

**`--config` 를 안 주면 `--source camera`(`--video` 포함)는 자동으로 `config/rtdetr_live.json`
을 쓴다** (2026-09-28 수정 — 예전엔 카메라도 데모용 `config/mvp.json` 기본값을 그대로 물려받아서,
`allow_mirrored_holes` 가 꺼진 채로 켜져 실제 카메라에서 180도 회전이 NG 로 나오는 버그가 있었다).
`demo`/`jsonl` 은 데모 시나리오가 맞춰 짜인 `config/mvp.json` 기본값 그대로 (`tests/test_web.py`
의 `ConfigDefaultTests`). 팀 원안(위쪽만, 좌우뒤집힘 불허)이 필요하면 `--config config/mvp.json`
으로 명시해서 자동 선택을 덮어쓴다.

## 영상과 추론 분리 — 2026-09-23

RT-DETR-l 은 CPU 에서 한 장 1~2초라 "캡처 → 추론 → 전송" 직렬 구조로는 영상이 1초에 한 번 갱신됐다.
`CameraSource(threaded=True)`(카메라 모드 기본): 영상은 카메라 속도로 계속 내보내고(최대 `max_fps` 20),
추론은 뒤 스레드가 **가장 최근 프레임만** 골라 돌려 마지막 결과를 매 프레임에 붙인다. 밀린 프레임은 버린다.
화면은 부드럽고 판정만 추론 시간만큼 늦게 갱신된다 — 진단 탭 "모델 추론 / 판정 지연" 행에 ms 로 나온다.
run_live.cmd 는 `--imgsz 480` 으로 띄운다(640 대비 약 2배 빠름, 부품이 크게 찍히므로 검출엔 충분).
그래도 판정이 1초 이상 늦으면 팀원에게 `yolo11n`(CPU 30~60ms) 재학습을 부탁하는 게 정석 — 코드는 그대로다.

## 녹화 영상으로 돌리기 (`--video`) — 2026-09-27

`python -m web.server --video 조립영상.mp4` (또는 `run_video.cmd` 에 영상을 끌어다 놓기). `CameraSource` 가 웹캠 대신 파일을 파일 fps 로 읽고,
추론·판정·화면은 카메라와 완전히 같다. 해상도는 파일 그대로(오버레이 좌표계).

- **끝나면 (`--video-end`)**: `hold`(기본) 마지막 장면을 계속 낸다 — 카메라가 완성품을 계속 보는 것과 같아서 PASS 와 [작업 완료] 가 남는다.
  `loop` 는 처음부터(PASS 가 곧 사라진다), `stop` 은 종료. 작업 화면에 "영상 끝 · 마지막 장면 유지 중" 칩이 뜬다 (`payload.video_at_end`).
- **[새 작업]·[작업 완료]** 는 영상을 처음으로 되감는다 (`CameraSource.reset()`) — 다음 제품 = 같은 영상 다시.
- **박스가 그려진 영상은 넣지 말 것**: `save_video_obb.cmd` 가 만든 `*_obb.mp4` 는 박스·라벨이 화면에 박혀 있어 모델이 부품을 못 잡는다 (재료 확인에서 멈춘다). 원본 영상을 넣는다.
- 검사: `tests/test_web.py::CameraSourceTests::test_video_end_hold_keeps_last_frame_and_reset_rewinds`.

## MES 연동 (`--mes-broker`) — 브랜치 yuseong/mes-mqtt

`python -m web.server --video 영상.mp4 --mes-broker localhost:1883 --station VIS-01` (또는 `run_station_mes.cmd`).
MQTT 로 MES(스프링부트 `pokayoke-mes`) 와 붙는다. 계약·규칙·이유는 [mes_mqtt.md](mes_mqtt.md).

- 작업지시가 레시피·수량을 정한다: 헤더 드롭다운 대신 `작업지시 WO-… · recipe_2 v3 · 3/10`, `/api/recipe/*` 는 409, 레시피 탭 버튼 잠김
- MES 가 내려준 레시피는 `data/mes/recipes/` 에 저장되고 같은 이름의 로컬 레시피(`config/recipes`) 를 덮는다
- 진행 중 작업지시가 없거나 다 채우면 판정 카드는 `대기` / `작업지시 완료`, [작업 완료] 는 409
- [작업 완료] → 제품 결과를 `data/mes/mes_link.db` 의 outbox 에 먼저 쓰고, 보내기 스레드가 QoS 1 로 보낸다. 브로커가 끊겨도 검사는 계속, 다시 붙으면 순서대로
- 헤더 점: 초록 연결됨, 빨강 끊김 (못 보낸 건수는 점에 마우스)
- 코드: `web/mes_link.py` (`MesLink` 판단 · `PahoTransport` 통신), 검사: `tests/test_mes_link.py` (가짜 전송 — 브로커 없이)
