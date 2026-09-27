# 비전 검사대 ↔ MES 메시지 계약 (MQTT, `pokayoke/1`)

검사대(파이썬, `web/mes_link.py`)와 MES(스프링부트, `pokayoke-mes`)가 **이 문서 하나**에 맞춰 만든다.
한쪽을 바꾸면 이 문서부터 고친다. 나중에 붙을 설비(SFaaS)·DT 도 같은 브로커·같은 규칙을 쓴다.

## 토픽

`{prefix}` 기본값 `factory`, `{station}` 예: `VIS-01`

| 토픽 | 방향 | QoS | retained | 내용 |
|---|---|---|---|---|
| `{prefix}/{station}/workorder` | MES → 검사대 | 1 | **예** | 지금 이 검사대가 할 작업지시. 빈 메시지 = 작업지시 없음(취소·완료 뒤 정리) |
| `{prefix}/{station}/ack` | 검사대 → MES | 1 | 아니오 | 작업지시를 받았음 / 거절 / 다 만들었음 |
| `{prefix}/{station}/result` | 검사대 → MES | 1 | 아니오 | 제품 1개가 끝났을 때 (작업자가 [작업 완료]) |
| `{prefix}/{station}/status` | 검사대 → MES | 1 | **예** | online / offline. offline 은 브로커가 대신 보낸다 (LWT) |

MES 는 `{prefix}/+/ack`, `{prefix}/+/result`, `{prefix}/+/status` 를 구독한다 — 검사대가 늘어도 MES 코드는 그대로.

## 메시지

모든 메시지에 `schema: "pokayoke/1"`, `station_id`. 검사대가 보내는 ack·result 에는 `event_id`(UUID) 와 `occurred_at`(ISO-8601, 시간대 포함 `+09:00`).

### workorder (MES → 검사대)
```json
{ "schema": "pokayoke/1", "work_order_id": "WO-20260928-001", "station_id": "VIS-01",
  "recipe": { "recipe_id": "recipe_2", "version": 3,
              "placements": [ {"mother_hole": 1, "bolt": "bolt_1", "part": "part_2hole"} ] },
  "quantity": 10, "released_at": "2026-09-28T09:00:00+09:00" }
```
레시피 내용을 작업지시에 같이 싣는다 — 레시피의 정답은 MES 이고, 검사대는 받은 것을 `data/mes_recipes/` 에 저장해 쓴다.

### ack (검사대 → MES)
```json
{ "schema": "pokayoke/1", "event_id": "…", "station_id": "VIS-01", "type": "ACCEPTED",
  "work_order_id": "WO-20260928-001", "done": 0, "quantity": 10, "reason": null,
  "occurred_at": "2026-09-28T09:00:02+09:00" }
```
`type`: `ACCEPTED`(적용함) · `REJECTED`(적용 못 함, `reason` 에 이유) · `COMPLETED`(수량을 다 채움) · `CANCELLED`(진행 중에 MES 가 비움)

### result (검사대 → MES)
```json
{ "schema": "pokayoke/1", "event_id": "…", "station_id": "VIS-01",
  "work_order_id": "WO-20260928-001", "product_seq": 3, "local_product_id": 17,
  "recipe_id": "recipe_2", "recipe_version": 3,
  "first_pass": false, "ng_count": 1, "material_ng_count": 0, "hold_count": 2,
  "ng_codes": ["WRONG_BOLT:H1"],
  "cycle_ms": 42100, "materials_ms": 9800, "assembly_ms": 32300,
  "occurred_at": "2026-09-28T09:12:03+09:00" }
```
[작업 완료] 는 PASS 확정일 때만 눌리므로, 보내지는 제품은 모두 최종 PASS 다. 도중의 NG 는 `ng_count`·`ng_codes` 로 남는다 (재작업 이력).

### status (검사대 → MES, retained)
```json
{ "schema": "pokayoke/1", "station_id": "VIS-01", "state": "online", "occurred_at": "…" }
```
검사대가 비정상 종료·네트워크 단절되면 브로커가 `{"schema":"pokayoke/1","station_id":"VIS-01","state":"offline"}` 를 대신 보낸다.

## 규칙

| 상황 | 검사대 | MES |
|---|---|---|
| 작업지시 도착, 진행 중인 것 없음 | 레시피 저장·적용, 열린 제품은 중단 처리, `ACCEPTED` | `RELEASED → IN_PROGRESS` |
| 같은 `work_order_id` 가 또 옴 (재연결 때 retained 재전달) | 무시 — 진행 수량 유지 | — |
| 다른 작업지시가 옴, 지금 것 진행 중 | 적용하지 않고 `REJECTED` (`BUSY`) | 한 검사대에 진행 중 작업지시는 하나만 발행한다 |
| 레시피가 규칙 위반 (H5 지정 등) | `REJECTED` (`INVALID_RECIPE`) | 레시피 등록 때 같은 규칙으로 막는다 |
| 빈 메시지 (retained 비움) | 진행 중이었으면 취소(`CANCELLED`), 끝났으면 그대로 | 취소·완료 때 보낸다 |
| 제품 1개 완료 | `done+1`, result 를 outbox 에 적고 보냄. 수량 채우면 `COMPLETED` | `event_id` 가 처음이면 저장·`done+1`. 수량 채우면 `COMPLETED` + retained 비움 |
| 같은 result 가 두 번 옴 (QoS 1 재전송) | — | `event_id` unique 로 두 번째는 무시 |
| 브로커 연결 끊김 | 검사는 계속, 보낼 것은 outbox(SQLite) 에 쌓였다가 재연결 뒤 순서대로 | status 가 offline 으로 보임 |

**수량의 정답은 MES** 다 (중복 제거된 result 개수). 검사대 화면의 `3/10` 은 보여 주기용이다.

## 왜 이렇게 (면접 포인트)

- **MQTT + retained 작업지시**: 검사대가 꺼져 있다 켜져도 브로커가 마지막 작업지시를 준다 — MES 가 검사대 주소를 몰라도 된다.
- **QoS 1 (최소 한 번)**: QoS 2 보다 가볍다. 대가로 생기는 중복은 `event_id` unique 로 막는다 (멱등).
- **outbox**: 브로커는 검사대가 연결조차 못 할 때의 결과를 지켜 주지 않는다. 먼저 로컬 DB 에 쓰고 나중에 보낸다.
- **LWT**: 설비 상태(online/offline) 를 MES 가 따로 물어보지 않아도 안다.
- **클라이언트 세션 유지** (`clean_session=false`, 고정 client id): 검사대가 끊긴 사이 MES 가 작업지시를 비워도(취소), 재연결 때 그 빈 메시지를 받는다.
