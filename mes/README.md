# smartfactory-mes

스마트팩토리 MES 서버 (Spring Boot 3.5 · Java 17+ · JPA/H2 · MQTT(Paho)).
설비와는 **MQTT**, 사람(관리 화면)과는 **REST**. 첫 번째로 붙은 설비는 비전 오조립 검사대(`SmartFactory_Vision_Project2`, 브랜치 `yuseong/mes-mqtt`).
나중에 SFaaS 설비·DT 도 같은 브로커·같은 토픽 규칙으로 붙인다.

```
 MES 콘솔(브라우저) ──REST──▶ MES (이 프로젝트, :8080) ──JPA──▶ H2 (data/mes)
                                   │  ▲
                        workorder  │  │ ack · result · status
                      (retained)   ▼  │
                         ┌──── MQTT 브로커 (Mosquitto, :1883) ────┐
                         │   factory/{station}/workorder|ack|result|status   │
                         └───────────────────────────────────────┘
                                   ▲  │
                                   │  ▼
                    비전 검사대 VIS-01 (파이썬, :8000) — 작업지시 → 레시피·수량, [작업 완료] → 실적
```

메시지 계약: [docs/mes_mqtt.md](docs/mes_mqtt.md) (검사대 쪽 `web/mes_link.py` 도 이 문서를 따른다)

## 실행 (윈도우, 이 순서)

> 저장소를 **영문 경로**에 둔다 (예: `C:\dev\SmartFactory_Vision_Project2`, 이 폴더는 그 안의 `mes/`). 경로에 한글이 있으면 윈도우에서 Gradle 테스트가 `ClassNotFoundException` 으로 전부 실패한다 — `run_mes.cmd`·`test_mes.cmd` 가 먼저 검사한다.

1. **브로커** — Mosquitto 설치(https://mosquitto.org/download/, Windows 64-bit) 후 `run_broker.cmd`.
   설치하면 윈도우 서비스로 이미 떠 있을 수 있다 — 그러면 스크립트가 "이미 떠 있음" 이라고 알려 준다. 도커면 `docker compose up -d`.
2. **MES** — `run_mes.cmd` (JDK 17~24 필요, **21 추천**. JDK 25 는 이 Gradle 8.14 가 못 돌린다 — IntelliJ 면 Gradle JVM 을 21 로). → http://localhost:8080
3. **검사대** — 비전 저장소 `yuseong/mes-mqtt` 브랜치의 `run_station_mes.cmd` 에 영상을 끌어다 놓기 (또는 더블클릭 = 웹캠). → http://localhost:8000
4. MES 콘솔에서 `VIS-01` · `recipe_1` · 수량 2 발행 → 검사대 헤더에 `작업지시 WO-… · recipe_1 v1 · 0/2` → PASS 에서 [작업 완료] 두 번 → 콘솔에 `2/2 COMPLETED`, 제품별 실적(첫 시도·NG 이력·사이클)

메모리가 빠듯하면 `run_mes_light.cmd`: jar 로 한 번 빌드하고 Gradle 을 끈 뒤 서버만 힙 384MB 로 (bootRun 은 Gradle + 서버, 자바 두 개).

테스트: `test_mes.cmd` (= `gradlew test`, 브로커 없이 돈다). DB 보기: http://localhost:8080/h2-console (JDBC URL `jdbc:h2:file:./data/mes`, 사용자 `sa`).

## REST

| 경로 | 뜻 |
|---|---|
| `GET /api/recipes` · `POST /api/recipes {recipe_id, placements}` | 레시피 목록 / 등록 (같은 id 면 버전 +1, 이전 버전 유지) |
| `POST /api/work-orders {station_id, recipe_id, recipe_version?, quantity}` | 작업지시 한 건. 설비가 비어 있으면 발행(커밋 뒤 retained), 진행 중·대기 중인 게 있으면 **대기열(QUEUED)** 끝에 |
| `POST /api/work-orders/batch {station_id, lines:[{recipe_id, recipe_version?, quantity}, …]}` | 여러 줄을 순서대로 (예: recipe_1×2 → recipe_2×3). 첫 줄 발행, 나머지 대기. 레시피 하나라도 틀리면 아무것도 등록 안 함 |
| `GET /api/work-orders?station=` · `GET /api/work-orders/{id}` | 목록 / 한 건 + 제품별 실적 |
| `POST /api/work-orders/{id}/cancel` | 취소. 진행 중이던 것이면 검사대는 중단하고 **대기열 다음 줄이 자동 발행**, 대기 중인 것이면 대기열에서만 빠짐 |

**대기열 규칙** — 검사대에 실리는 작업지시는 늘 하나(RELEASED/IN_PROGRESS). 그것이 끝나면(수량 채움 · 취소 · 거절) MES 가 대기열 맨 앞(작업지시 번호 순)을 발행하고 retained 를 바꿔 싣는다. 검사대는 "지금 것이 끝났으면 새 작업지시를 받는다" 는 기존 규칙 그대로라 바뀐 게 없다. 거절 이유가 `BUSY`(검사대에 MES 가 모르는 작업이 남음) 면 다음 줄도 똑같이 거절될 테니 넘기지 않고 멈춘다. 작업지시 메시지의 `next` 에 대기열이 실린다 (검사대 화면의 "다음 작업" 표시용).
| `GET /api/stations` · `GET /api/health` | 설비 연결 상태(LWT) / 브로커 연결 |

## 구조

| 패키지 | 하는 일 |
|---|---|
| `mqtt` | `MqttGateway`(인터페이스) · `PahoMqttGateway`(실제) · `NoopMqttGateway`(브로커 없이) · `StationMessageHandler`(토픽 → 서비스) |
| `workorder` | `WorkOrder`(상태 전이는 엔티티 메서드로만) · `WorkOrderService`(발행·취소·ack·result) · `WorkOrderPublisher`(retained 를 DB 와 맞춤) |
| `recipe` | 버전 관리되는 기준정보 · 검사대와 같은 검증 규칙(H1~H4, 부품 종류) · 시작 때 seed |
| `result` | 제품 실적 (`event_id` unique) |
| `station` | 설비 연결 상태 · ack 기록(`event_id` PK) |

## 판단 기준 (면접에서 설명할 것)

- **왜 MQTT**: 설비는 꺼졌다 켜지고 주소가 바뀐다. retained 작업지시면 설비가 켜질 때 브로커가 바로 준다. LWT 로 설비 상태를 따로 묻지 않는다. 나중 설비·DT 도 같은 브로커에 구독만 하면 된다.
- **QoS 1 + 멱등**: 최소 한 번 전달이라 같은 결과가 두 번 올 수 있다 → `event_id` 로 거르고, DB unique 가 마지막 방어선. QoS 2 는 느리고 이 규모엔 과하다.
- **수량의 정답은 MES**: 중복 제거된 result 개수로만 센다. 검사대의 COMPLETED 보고와 다르면 경고 로그.
- **발행은 커밋 뒤** (`AfterCommit`): 롤백됐는데 설비는 작업지시를 받은 상태를 막는다. 커밋 뒤 읽기는 `REQUIRES_NEW`.
- **retained 는 "원하는 상태" 를 통째로**: 발행을 한 번 놓쳐도(브로커 끊김) 재연결·다음 변경 때 `syncAll/syncStation` 이 DB 기준으로 다시 맞춘다.
- **레시피는 고치지 않고 버전을 올린다**: 실적에 `recipe_version` 이 남아 "무슨 기준으로 검사했나" 를 추적한다.

## AI 가 짠 코드에서 의심할 곳

- Paho `messageArrived` 에서 예외가 밖으로 나가면 연결이 끊긴다 → 전부 잡는지.
- 콜백 스레드 안에서 발행 완료를 기다리면 교착 → 비동기 클라이언트, 토큰 대기 없음.
- `automaticReconnect` 는 처음 연결 실패엔 안 돈다 → 직접 재시도하는지 (`PahoMqttGateway.connect`).
- 연결을 `@PostConstruct` 에서 하면 핸들러 등록 전에 세션의 메시지가 와서 버려진다 → `ApplicationReadyEvent`.
- id 를 직접 정하는 엔티티 + `@Version` 이 primitive 면 새 저장이 merge 로 가서 Hibernate 6.6 에서 예외 → `Long`.
- 윈도우에서 한글 주석 컴파일 깨짐 → `options.encoding = 'UTF-8'`.

## 터졌을 때 볼 곳

| 증상 | 볼 곳 |
|---|---|
| 콘솔 상단 "브로커 연결 안 됨" | Mosquitto 가 떠 있나 (`netstat -ano \| findstr 1883`), `mes.mqtt.broker-uri` |
| 발행했는데 검사대가 그대로 | 검사대 헤더 점이 빨강인지(브로커), 검사대 창 로그, 토픽 `factory/VIS-01/workorder` (MQTT Explorer 로 보면 retained 가 보인다) |
| 작업지시가 REJECTED | 콘솔의 이유: `BUSY`(검사대에 다른 작업지시) · `INVALID_RECIPE` |
| 실적이 두 배 | `product_result.event_id` unique 가 있는지 (H2 콘솔) |
| 실적이 모자람 | 검사대 `data/mes/mes_link.db` 의 outbox 에 `sent_at` 이 빈 줄 |
| 빌드 실패 `unmappable character` | build.gradle 의 UTF-8 설정 |
| 테스트 전부 `ClassNotFoundException` (컴파일은 됨) | 폴더 경로에 한글 — 영문 경로로 옮기기 |
| `.cmd` 창이 열리자마자 꺼짐 | `( … )` 블록 안 echo 에 괄호가 있으면 cmd 가 블록을 일찍 닫는다 — 스크립트는 goto 로만 |

## 검증 상태 (2026-09-27)

- 작성한 곳에서는 패키지 저장소가 막혀 **스프링 빌드·테스트를 돌리지 못했다.** 대신: 스프링·JPA·Paho API 를 흉내 낸 선언으로 전체를 `javac --release 17` 로 타입 검사(통과), 메시지 레코드는 실제 Jackson 으로 검사대(파이썬) 가 만든 ack/result 를 읽고 MES 가 만든 작업지시를 검사대가 받는 것까지 확인.
- **PC 에서 처음 할 것**: `test_mes.cmd` → 통과 확인 → `run_broker.cmd` · `run_mes.cmd` · 검사대 순서로 끝에서 끝까지.
