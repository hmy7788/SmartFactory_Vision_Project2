package com.smartfactory.mes.system;

import java.util.Map;

import com.smartfactory.mes.mqtt.MqttGateway;
import com.smartfactory.mes.mqtt.MqttProperties;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** 콘솔 상단의 "브로커 연결" 표시용. */
@RestController
public class SystemController {

    private final MqttGateway gateway;
    private final MqttProperties props;

    public SystemController(MqttGateway gateway, MqttProperties props) {
        this.gateway = gateway;
        this.props = props;
    }

    @GetMapping("/api/health")
    public Map<String, Object> health() {
        return Map.of("mqtt_enabled", props.enabled(), "mqtt_connected", gateway.isConnected(),
                "broker", props.brokerUri(), "topic_prefix", props.topicPrefix());
    }
}
