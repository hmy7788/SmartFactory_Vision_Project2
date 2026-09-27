# 웹 UI (web/)

작업자 화면 + 이력·분석·진단 탭. 카메라·모델 없이도 돈다 (합성 데모). 코어(`src/`)는 건드리지 않는다.

## 실행

```bash
pip install -r requirements.txt          # fastapi(→ starlette) + uvicorn[standard](→ websockets) 가 들어 있다
python -m web.server                     # 합성 데모, http://localhost:8000
python -m web.server --speed 2           # 데모 시나리오 2배속 (발표 리허설)
python -m web.server --source jsonl --jsonl detections.jsonl     # 기록한 검출 재생
python -m web.server --source camera     # 웹캠 + YOLO-OBB (model/yolo_obb_parts.pt 가 있어야 함)
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
| 작업 | 작업자 | 영상+오버레이(맞음/틀림/아직/비움), 재료 표, 자리별 표, 큰 판정 카드. 확률·클래스 코드 없음. PASS 확정 때만 **작업 완료** 버튼 → 기록 후 `reset()`. NG 는 치우면 자동 해제(버튼 없음). HOLD 는 호박색(불량 아님) |
| 레시피 | 작업자·리더 | 레시피별 정답 자리·부품 그림과 재료 수량 |
| 이력 | 리더 | 제품별 결과(COMPLETED/ABANDONED, 사이클, NG·HOLD 횟수, 일발통과)와 타임라인(이벤트 순서) |
| 분석 | 리더·품질 | FPY(전체·일별), 사이클타임 분포(재료/조립), 오류 파레토(조립·재료), 자리×오류 히트맵, NG 복구 시간 |
| 진단 | 개발자 | 실시간: 코어 후보/확정, 안정화, issue 코드 원문, 검출 confidence, ROI 폴리곤, 각도. 시스템: HOLD 사유, confidence 분포, 프레임 지연·gap 시계열, 현재 config |

대표 오류(작업 화면의 큰 글씨) 선정: `WRONG_*` > `UNEXPECTED_COMPONENT`/`EXTRA_COMPONENT` > `PART_ORIENTATION_ERROR` > `MISSING_*`, 같은 급이면 낮은 H 번호. 나머지는 "외 N건". 코드는 `app.js` 의 `PRIORITY`/`primaryIssue`.

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

`CameraSource` 는 구현돼 있다. **가중치 파일 하나만** 있으면 된다:

```bash
pip install -r requirements.txt                      # ultralytics, opencv, uvicorn[standard], fastapi
cp <받은 파일>.pt model/yolo_obb_parts.pt
python -m web.server --source camera                 # 카메라 0번, 1280x720, conf 0.25, imgsz 640
python -m web.server --source camera --camera 1 --camera-size 1920x1080 --weights model/best.pt
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
- 오버레이의 H 라벨·링은 `stable` 이거나 HOLD 일 때만 갱신한다 (후보가 깜빡이는 걸 작업자에게 안 보이려고). 진단 탭은 매 프레임 갱신.
- 헤더(레시피 select) 는 payload 의 모양이 바뀔 때만 다시 그린다 — 매 프레임 그리면 select 를 조작할 수 없다.
- 하드 SVG 차트(외부 라이브러리 없음). 데이터가 수백 제품을 넘으면 `/api/analytics` 의 `days` 를 줄이거나 Store 쿼리에 인덱스를 보태야 한다.
- 브라우저 1개 기준으로 확인했다. 여러 브라우저가 붙으면 `Hub` 가 전부에 fan-out 하지만 부하는 재지 않았다.

## AABB(detect) 가중치로 돌리기 — 2026-09-23

팀원이 준 `best.pt` 는 RT-DETR-l **detect(AABB)** 모델이다 (OBB 아님, 클래스 이름은 우리 이름 그대로). 어댑터가 `.boxes` 도 받도록 바꿨다:
각도는 0 으로 넣고, 세로로 긴 박스는 코어의 `major_axis` 가 90° 로 읽는다 → **똑바로 놓는(지그) 시연은 그대로 된다.**
완성체 사진 100장(aabb 라벨)을 코어에 넣어 확인: 똑바로 놓인 60장 전부 자기 레시피 PASS, 다른 레시피 PASS 0건, 기울어진 40장은 보류(오판 없음).

삐뚤게 놓는 경우는 `--refine-angles` (run_live.cmd 의 Tilt 질문에 y): `src/vision/angle_refiner.py` 가 OpenCV 로 Mother·부품 각도를 붙인다.
같은 100장에서 82장 PASS, 오판 0. 안 되는 18장은 전부 부품이 Mother 아래쪽으로 오게 뒤집어 놓은 사진 — 코어가 각도를 ±90° 로 접어
H1/H5 를 못 가르는 규약 문제라 코어를 바꿔야 한다(팀 결정). `config/mvp.json` 의 `max_mother_angle_deg`(15) 를 넘는 기울기는 보류.

    python -m scripts.replay_photos ..\aabb                    # 라벨로 코어 판정 재현 (모델 없이)
    python -m scripts.replay_photos ..\aabb --refine --max-angle 90 --draw out   # 각도 보정 + 그림

## 영상과 추론 분리 — 2026-09-23

RT-DETR-l 은 CPU 에서 한 장 1~2초라 "캡처 → 추론 → 전송" 직렬 구조로는 영상이 1초에 한 번 갱신됐다.
`CameraSource(threaded=True)`(카메라 모드 기본): 영상은 카메라 속도로 계속 내보내고(최대 `max_fps` 20),
추론은 뒤 스레드가 **가장 최근 프레임만** 골라 돌려 마지막 결과를 매 프레임에 붙인다. 밀린 프레임은 버린다.
화면은 부드럽고 판정만 추론 시간만큼 늦게 갱신된다 — 진단 탭 "모델 추론 / 판정 지연" 행에 ms 로 나온다.
run_live.cmd 는 `--imgsz 480` 으로 띄운다(640 대비 약 2배 빠름, 부품이 크게 찍히므로 검출엔 충분).
그래도 판정이 1초 이상 늦으면 팀원에게 `yolo11n`(CPU 30~60ms) 재학습을 부탁하는 게 정석 — 코드는 그대로다.
