package com.smartfactory.mes.mqtt;

import java.util.function.BiConsumer;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** mes.mqtt.enabled=false — 브로커 없이 REST·DB 만 돌려 볼 때. 발행은 로그로만. */
@Component
@ConditionalOnProperty(prefix = "mes.mqtt", name = "enabled", havingValue = "false")
public class NoopMqttGateway implements MqttGateway {

    private static final Logger log = LoggerFactory.getLogger(NoopMqttGateway.class);

    @Override
    public void publish(String topic, String payload, int qos, boolean retained) {
        log.info("[MQTT 꺼짐] {} retained={} {}", topic, retained, payload.isEmpty() ? "(비움)" : payload);
    }

    @Override
    public boolean isConnected() {
        return false;
    }

    @Override
    public void setInboundListener(BiConsumer<String, String> listener) {
    }

    @Override
    public void setConnectedListener(Runnable listener) {
    }
}
