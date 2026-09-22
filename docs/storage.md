# 저장 계층 (web/store.py) — 담당: 최유성

`state_machine_development_guidelines.md` 의 `database/  # 다른 담당: 이벤트 저장` 자리. 코어(`src/`)는 건드리지 않는다.
`Snapshot` 을 받아 **변화만** SQLite 에 쓰고, 이력·분석·진단 탭이 읽을 쿼리를 함수로 제공한다.

```powershell
python -m unittest tests.test_store -v      # 실제 코어(InspectionService) 흐름으로 8개 검증, 모델·GPU 불필요
```

## 표 다섯 개 (web/schema.sql)

| 표 | 한 행 | 생기는 때 |
|---|---|---|
| `runs` | 프로그램 세션 — 모델 파일·`mvp.json` 통째·보정 상태 | 켤 때 |
| `products` | 제품 1대 + 닫을 때 계산한 요약(사이클·NG·보류·첫 시도) | `open_product` / `close_product` |
| `events` | 상태가 바뀐 순간. `snapshot.events` 한 건 = 한 행 | `record()` 에 events 가 있을 때 |
| `event_issues` | 이벤트 안 오류 1건 (`issues_json` 을 펼친 것) | events 와 같이 |
| `metrics` | 1분 버킷 — FPS·지연 p50/p95·gap 초과·HOLD 프레임 | 분이 바뀔 때 |

## 파이프라인에서 부르는 순서

```python
store   = Store("data/pokayoke.db")                       # data/ 는 .gitignore 대상
run     = store.open_run("model/yolo_obb_parts.pt", config)
product = store.open_product(run, recipe.recipe_id, started_ms=first_frame_ts)

snapshot = service.update(frame)                          # 매 프레임
store.record(product, snapshot, latency_ms=now_ms - frame.timestamp_ms)   # events 없으면 0 — 안 씀
store.frame(run, infer_ms, total_ms, gap_ms, hold=snapshot.candidate.status is Status.HOLD)

store.close_product(product, closed_ms=now_ms)                       # [작업 완료] 버튼
store.close_product(product, closed_ms=now_ms, result="ABANDONED")   # [새 작업] 버튼 (또는 open_product 가 자동으로)
store.close_run(run)
```

`record()` 의 `mother_angle_deg`: 각도 초과 HOLD 는 geometry 가 비어 각도를 모른다. 파이프라인이 Mother 검출에
`mother_frame.major_axis()` 를 한 번 더 불러 넘겨 주면 진단 탭에 "26°" 가 찍힌다. 안 넘기면 NULL.

## 탭 ↔ 함수

| 탭 | 함수 |
|---|---|
| 이력 | `history(limit, recipe_id, result, ng_only, hold_only)` · `timeline(product_id)` |
| 분석 | `fpy(days)` · `cycle(days)` · `pareto(days)` · `heatmap(days)` · `recovery(days)` |
| 진단 | `hold_reasons(days)` · `confidence(days)` · `metrics(hours)` |

## 왜 이렇게 했나 (판단 기준)

- **프레임이 아니라 이벤트.** 판정은 0.4초 안정화 뒤에만 바뀐다. 데모 66프레임 → 이벤트 9건. 제품당 한 자릿수라 동기 INSERT 로 충분하고, 그래서 큐·스레드가 없다. 프레임마다 쓰게 되는 순간 이 판단은 뒤집힌다.
- **제품 = `close_product` 호출.** PASS 는 빼면 IN_PROGRESS 로 돌아갔다가 또 PASS 가 된다. 인수인계 문서: "PASS 이벤트 수를 제품 수로 세지 않는다".
- **NG·HOLD 는 에피소드로 센다.** NG → HOLD → NG 는 한 번. 전환 프레임(ASSEMBLY_STARTED)의 HOLD 는 설계상 HOLD 라 제외.
- **`issues_json` 원본 + `event_issues` 펼친 표, 둘 다.** 파레토·히트맵은 `GROUP BY code, hole_id` 한 줄이어야 한다. 원본은 재현용.
- **`products` 요약 컬럼은 닫을 때 한 번 계산.** 읽기는 많고 쓰기는 한 번.
- **시간 두 벌.** `ts_ms`(코어의 단조 증가 ms)로만 길이 계산. `ts_utc` 는 `datetime('now')` 와 같은 `YYYY-MM-DD HH:MM:SS` 형식이라 SQL 에서 문자열 비교로 기간을 자른다.
- **작업자 ID 컬럼 없음.** 지뢰밭 문서의 "개인별 통계는 기술적으로 불가능" 이 참이 되도록.
- **`runs` 에 설정을 통째로.** "FPY 가 올랐는데 작업자가 익숙해진 건지 모델을 바꾼 건지" 는 이 표 없이는 못 답한다.

## AI 가 고쳐 준 코드에서 의심할 곳

- `service.update()` 바로 다음 줄의 `INSERT` 가 **프레임마다** 실행되게 바뀌었나 → 추론 루프가 디스크를 기다린다.
- `status == 'PASS'` 를 세서 제품 수로 쓰나.
- 코어 `event_id` 를 그대로 키로 쓰나 → reset 마다 1부터라 겹친다. 반드시 `product_id` 와 함께.
- `datetime.now()` 로 사이클을 재나 → NTP 가 시각을 당기면 음수.
- `PRAGMA foreign_keys=ON` 이 사라졌나 → SQLite 기본은 OFF. 고아 행이 생겨도 조용하다.
- **named placeholder(`:a`) 에 tuple 을 넘기나** → 예외 없이 엉뚱한 값이 바인딩되고 UPDATE 가 0행을 고친다. 이 저장소에서 실제로 났던 버그고 `test_close_product_summary` 가 잡았다.

## 돌리다 이상하면

| 증상 | 먼저 볼 곳 |
|---|---|
| 사이클이 0·음수 | `started_ms`/`closed_ms` 에 벽시계(ms)가 섞임. 둘 다 코어 `timestamp_ms` 계열이어야 |
| 이력에 제품이 두 배 | PASS 이벤트를 제품으로 셈 |
| FPY 100% 인데 NG 이벤트 있음 | `first_pass` 를 마지막 status 로 계산 — `ng_count` 로 |
| `close_product` 뒤에도 `result='OPEN'` | UPDATE 파라미터가 dict 가 아니라 tuple 로 감 (위 항목) |
| 타임라인 순서가 섞임 | `core_seq` 로 정렬 — `ts_ms, event_id` 로 |
| `IntegrityError: FOREIGN KEY` | `open_product` 전에 `record` 를 부름, 또는 다른 run 의 product_id |
| DB 파일이 4 KB 인데 행이 있음 | WAL 모드라 `-wal` 파일에 있음. 정상. `PRAGMA wal_checkpoint` 로 합쳐짐 |
| 분석 탭이 전부 0 | `ts_utc` 형식이 `datetime('now')` 와 다름 (`T` 구분자·타임존 접미사) |

## 아직 없는 것

- `web/pipeline.py`·`server.py` — 카메라 → 모델 → 코어 → 웹소켓. 이 파일이 `Store` 를 부른다.
- NG 확정 프레임 JPEG 저장 (`events.frame_path`) — 파이프라인이 파일을 쓰고 경로만 넘기면 된다. `outputs/` 는 gitignore.
- 과검율 — 수동 통과가 없어서 "시스템이 틀렸다" 를 표시할 방법이 없다. 넣지 않았다.
