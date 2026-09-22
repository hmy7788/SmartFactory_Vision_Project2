# 웹 UI (web/)

작업자 화면 + 이력·분석·진단 탭. 카메라·모델 없이도 돈다 (합성 데모). 코어(`src/`)는 건드리지 않는다.

## 실행

```bash
pip install -r requirements.txt          # fastapi(→ starlette) + uvicorn[standard](→ websockets) 가 들어 있다
python -m web.server                     # 합성 데모, http://localhost:8000
python -m web.server --speed 2           # 데모 시나리오 2배속 (발표 리허설)
python -m web.server --source jsonl --jsonl detections.jsonl     # 기록한 검출 재생
python -m web.server --source camera --weights model/yolo_obb_parts.pt   # CameraSource 를 채운 뒤
python -m unittest tests.test_web        # 8개, 약 20초
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
| `web/source.py` | `DemoSource`(합성 시나리오) · `JsonlSource`(기록 재생) · `CameraSource`(**모델 담당이 채움**). 셋 다 `frames()` 가 `(DetectionFrame, JPEG|None)` 을 낸다 |
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
| `geometry{pose,holes,bolt_rois,part_rois}` | Snapshot | Mother-local 기하. HOLD(각도 초과·Mother 없음) 면 `{}` |
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

## CameraSource 채우기 (모델 담당)

`web/source.py` 의 `CameraSource.frames()` 하나만 채우면 `--source camera` 로 붙는다. docstring 에 뼈대가 있다. 지킬 것:

1. `timestamp_ms` 는 **캡처 시각**, `now_ms()`(monotonic) 로. 추론이 끝난 시각이 아니다. 코어의 frame gap(250ms) 판정이 이 값에 걸려 있다.
2. `from_ultralytics(result, frame_id, ts, mapping)` 의 xywhr 이 **원본 픽셀** 이어야 한다. 추론 전에 resize 했으면 되돌린다. `frame_size` 도 원본 해상도.
3. 모델 conf 는 낮게(0.25) 두고 판정 임계는 config `confidence_threshold`(0.5) 가 거른다 — 진단 탭의 confidence 분포가 임계 근처 검출을 보여 줘야 임계를 고를 수 있다.
4. 카메라 오류면 `DetectionFrame(frame_id, ts, (), input_valid=False)` 를 낸다 → 코어가 `INPUT_UNAVAILABLE` HOLD.
5. `jpeg` 를 같이 내면 `/video` 가 살아나고 오버레이가 실제 영상 위에 얹힌다. JPEG 품질 80, 인코딩 시간은 `total_ms` 에 포함된다.

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
