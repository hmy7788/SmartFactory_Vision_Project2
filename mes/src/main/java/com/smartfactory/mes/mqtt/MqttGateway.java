package com.smartfactory.mes.mqtt;

import java.util.function.BiConsumer;

/**
 * MES 가 브로커와 주고받는 창구. 실제 구현(PahoMqttGateway) 과 테스트용 가짜를 바꿔 끼울 수 있게 인터페이스로.
 */
public interface MqttGateway {

    /** payload 가 빈 문자열이고 retained=true 면 그 토픽의 retained 메시지를 지운다 (작업지시 없음). */
    void publish(String topic, String payload, int qos, boolean retained);

    boolean isConnected();

    /** (topic, payload) — 설비가 보낸 ack/result/status */
    void setInboundListener(BiConsumer<String, String> listener);

    /** 연결될 때마다 (처음 + 재연결) — 작업지시를 다시 맞춰 놓는다 */
    void setConnectedListener(Runnable listener);
}
