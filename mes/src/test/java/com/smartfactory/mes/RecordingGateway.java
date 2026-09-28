package com.smartfactory.mes;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.BiConsumer;

import com.smartfactory.mes.mqtt.MqttGateway;

/** 테스트용 브로커 흉내: 발행한 것을 기록만 한다. */
public class RecordingGateway implements MqttGateway {

    public record Msg(String topic, String payload, int qos, boolean retained) {
    }

    public final List<Msg> sent = new CopyOnWriteArrayList<>();

    @Override
    public void publish(String topic, String payload, int qos, boolean retained) {
        sent.add(new Msg(topic, payload, qos, retained));
    }

    @Override
    public boolean isConnected() {
        return true;
    }

    @Override
    public void setInboundListener(BiConsumer<String, String> listener) {
    }

    @Override
    public void setConnectedListener(Runnable listener) {
    }

    public Msg last(String topic) {
        for (int i = sent.size() - 1; i >= 0; i--) {
            if (sent.get(i).topic().equals(topic)) {
                return sent.get(i);
            }
        }
        throw new AssertionError("발행 없음: " + topic + "  (전체: " + sent + ")");
    }
}
