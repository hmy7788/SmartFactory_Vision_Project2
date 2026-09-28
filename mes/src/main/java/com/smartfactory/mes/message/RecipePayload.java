package com.smartfactory.mes.message;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RecipePayload(
        @JsonProperty("recipe_id") String recipeId,
        @JsonProperty("version") int version,
        @JsonProperty("placements") List<Placement> placements) {
}
