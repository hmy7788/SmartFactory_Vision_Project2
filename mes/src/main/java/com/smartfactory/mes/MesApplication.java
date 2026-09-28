package com.smartfactory.mes;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * 스마트팩토리 MES — 설비(비전 검사대 등)와는 MQTT, 사람(관리 화면)과는 REST.
 * 메시지 계약은 docs/mes_mqtt.md (검사대 저장소와 같은 문서).
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class MesApplication {
    public static void main(String[] args) {
        SpringApplication.run(MesApplication.class, args);
    }
}
