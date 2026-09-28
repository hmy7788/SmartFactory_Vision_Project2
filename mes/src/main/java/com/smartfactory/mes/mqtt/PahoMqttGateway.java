package com.smartfactory.mes.mqtt;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.BiConsumer;

import jakarta.annotation.PreDestroy;

import org.eclipse.paho.client.mqttv3.IMqttActionListener;
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.IMqttToken;
import org.eclipse.paho.client.mqttv3.MqttAsyncClient;
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * Paho(비동기 클라이언트) 로 브로커에 붙는다.
 *
 * 의심 지점 / 판단:
 *  - 연결은 ApplicationReadyEvent 뒤에: 핸들러가 리스너를 등록하기 전에 연결되면, 세션에 쌓여 있던 메시지가 버려진다.
 *  - cleanSession=false + 고정 clientId: MES 가 꺼져 있는 동안 설비가 보낸 QoS1 결과를 브로커가 들고 있다가 준다.
 *  - automaticReconnect 는 "한 번 붙었다가 끊긴 뒤" 에만 동작한다 — 처음 연결 실패는 직접 다시 시도한다.
 *  - messageArrived 에서 예외가 밖으로 나가면 Paho 가 연결을 끊는다 — 여기서 전부 잡는다.
 *  - 콜백 스레드 안에서 발행 완료를 기다리지 않는다 (비동기 클라이언트, 토큰 대기 없음) — 기다리면 교착.
 */
@Component
@ConditionalOnProperty(prefix = "mes.mqtt", name = "enabled", havingValue = "true", matchIfMissing = true)
public class PahoMqttGateway implements MqttGateway, MqttCallbackExtended {

    private static final Logger log = LoggerFactory.getLogger(PahoMqttGateway.class);

    private final MqttProperties props;
    private final ScheduledExecutorService retry = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "mqtt-retry");
        t.setDaemon(true);
        return t;
    });
    private volatile BiConsumer<String, String> inbound = (topic, payload) -> { };
    private volatile Runnable onConnected = () -> { };
    private volatile MqttAsyncClient client;

    public PahoMqttGateway(MqttProperties props) {
        this.props = props;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void start() throws MqttException {
        client = new MqttAsyncClient(props.brokerUri(), props.clientId(), new MemoryPersistence());
        client.setCallback(this);
        connect();
    }

    private void connect() {
        MqttConnectOptions options = new MqttConnectOptions();
        options.setCleanSession(false);
        options.setAutomaticReconnect(true);
        options.setKeepAliveInterval(30);
        options.setConnectionTimeout(5);
        try {
            client.connect(options, null, new IMqttActionListener() {
                @Override
                public void onSuccess(IMqttToken token) {
                    // 구독·재발행은 connectComplete 에서 (재연결 때도 같은 길로)
                }

                @Override
                public void onFailure(IMqttToken token, Throwable e) {
                    log.warn("MQTT 연결 실패 ({}): {} — 5초 뒤 다시", props.brokerUri(), e.getMessage());
                    retry.schedule(PahoMqttGateway.this::connect, 5, TimeUnit.SECONDS);
                }
            });
        } catch (MqttException e) {
            log.warn("MQTT 연결 시도 실패 ({}): {} — 5초 뒤 다시", props.brokerUri(), e.getMessage());
            retry.schedule(this::connect, 5, TimeUnit.SECONDS);
        }
    }

    @Override
    public void connectComplete(boolean reconnect, String serverURI) {
        log.info("MQTT {} {}", reconnect ? "재연결" : "연결", serverURI);
        String p = props.topicPrefix();
        try {
            client.subscribe(new String[] {p + "/+/ack", p + "/+/result", p + "/+/status"}, new int[] {1, 1, 1});
        } catch (MqttException e) {
            log.error("구독 실패", e);
        }
        try {
            onConnected.run();
        } catch (RuntimeException e) {
            log.error("연결 뒤 작업지시 맞추기 실패", e);
        }
    }

    @Override
    public void connectionLost(Throwable cause) {
        log.warn("MQTT 연결 끊김: {} — 자동 재연결", cause == null ? "?" : cause.getMessage());
    }

    @Override
    public void messageArrived(String topic, MqttMessage message) {
        try {
            inbound.accept(topic, new String(message.getPayload(), StandardCharsets.UTF_8));
        } catch (RuntimeException e) {
            log.error("메시지 처리 실패 {} : {}", topic, e.toString(), e);
        }
    }

    @Override
    public void deliveryComplete(IMqttDeliveryToken token) {
    }

    @Override
    public void publish(String topic, String payload, int qos, boolean retained) {
        MqttAsyncClient c = client;
        if (c == null || !c.isConnected()) {
            log.warn("MQTT 미연결 — {} 발행 못 함 (재연결 때 작업지시는 다시 맞춘다)", topic);
            return;
        }
        try {
            c.publish(topic, payload.getBytes(StandardCharsets.UTF_8), qos, retained);
        } catch (MqttException e) {
            log.warn("발행 실패 {}: {}", topic, e.getMessage());
        }
    }

    @Override
    public boolean isConnected() {
        MqttAsyncClient c = client;
        return c != null && c.isConnected();
    }

    @Override
    public void setInboundListener(BiConsumer<String, String> listener) {
        this.inbound = listener;
    }

    @Override
    public void setConnectedListener(Runnable listener) {
        this.onConnected = listener;
    }

    @PreDestroy
    public void stop() {
        retry.shutdownNow();
        MqttAsyncClient c = client;
        if (c == null) {
            return;
        }
        try {
            if (c.isConnected()) {
                c.disconnect().waitForCompletion(2000);
            }
            c.close();
        } catch (MqttException e) {
            log.debug("MQTT 종료 중: {}", e.getMessage());
        }
    }
}
