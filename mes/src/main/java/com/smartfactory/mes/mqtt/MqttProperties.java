package com.smartfactory.mes.mqtt;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** application.yml 의 mes.mqtt.* */
@ConfigurationProperties(prefix = "mes.mqtt")
public record MqttProperties(
        @DefaultValue("true") boolean enabled,
        @DefaultValue("tcp://localhost:1883") String brokerUri,
        @DefaultValue("mes-server") String clientId,
        @DefaultValue("factory") String topicPrefix) {

    /** factory/VIS-01/workorder */
    public String topic(String stationId, String kind) {
        return topicPrefix + "/" + stationId + "/" + kind;
    }
}
