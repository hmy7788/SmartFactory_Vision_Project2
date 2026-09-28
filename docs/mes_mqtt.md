# MES ↔ 검사대 MQTT 메시지

문서는 MES 쪽 하나만 둔다 → [mes/docs/mes_mqtt.md](../mes/docs/mes_mqtt.md)
(토픽 · 작업지시/ack/result/status 메시지 · 대기열(`next`) · 재연결·재전송 규칙)

검사대 쪽 구현: `web/mes_link.py` (작업지시 → 레시피·수량, 보낼 목록 outbox, 결과 전송), 테스트 `tests/test_mes_link.py`.
