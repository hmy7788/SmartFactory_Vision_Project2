package com.smartfactory.mes.recipe;

import java.time.Instant;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.smartfactory.mes.message.Placement;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/recipes")
public class RecipeController {

    private final RecipeService recipes;

    public RecipeController(RecipeService recipes) {
        this.recipes = recipes;
    }

    @GetMapping
    public List<RecipeView> list() {
        return recipes.all().stream().map(this::view).toList();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public RecipeView create(@Valid @RequestBody CreateRecipe request) {
        return view(recipes.create(request.recipeId(), request.placements()));
    }

    private RecipeView view(Recipe r) {
        return new RecipeView(r.getRecipeId(), r.getVersion(), recipes.placements(r), r.getCreatedAt());
    }

    public record CreateRecipe(
            @NotBlank @JsonProperty("recipe_id") String recipeId,
            @NotEmpty @JsonProperty("placements") List<Placement> placements) {
    }

    public record RecipeView(
            @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("version") int version,
            @JsonProperty("placements") List<Placement> placements,
            @JsonProperty("created_at") Instant createdAt) {
    }
}
