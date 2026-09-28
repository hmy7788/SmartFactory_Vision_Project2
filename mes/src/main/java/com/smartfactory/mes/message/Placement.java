package com.smartfactory.mes.message;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 레시피의 한 자리: H1~H4 에 어떤 볼트·파트 */
public record Placement(
        @JsonProperty("mother_hole") int motherHole,
        @JsonProperty("bolt") String bolt,
        @JsonProperty("part") String part) {
}
