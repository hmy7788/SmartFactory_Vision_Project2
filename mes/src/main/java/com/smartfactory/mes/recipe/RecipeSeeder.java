package com.smartfactory.mes.recipe;

import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartfactory.mes.message.Placement;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Component;

/** 레시피가 하나도 없으면 seed/recipe_*.json (검사대의 config/recipes 와 같은 내용) 을 v1 로 넣는다. */
@Component
public class RecipeSeeder implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(RecipeSeeder.class);

    private final RecipeRepository repo;
    private final RecipeService recipes;
    private final ObjectMapper json;

    public RecipeSeeder(RecipeRepository repo, RecipeService recipes, ObjectMapper json) {
        this.repo = repo;
        this.recipes = recipes;
        this.json = json;
    }

    @Override
    public void run(ApplicationArguments args) throws IOException {
        if (repo.count() > 0) {
            return;
        }
        Resource[] files = new PathMatchingResourcePatternResolver().getResources("classpath:seed/recipe_*.json");
        Arrays.sort(files, Comparator.comparing(Resource::getFilename));
        for (Resource file : files) {
            try (InputStream in = file.getInputStream()) {
                SeedRecipe seed = json.readValue(in, SeedRecipe.class);
                recipes.create(seed.recipeId(), seed.placements());
                log.info("레시피 넣음: {} v1", seed.recipeId());
            }
        }
    }

    record SeedRecipe(
            @JsonProperty("recipe_id") String recipeId,
            @JsonProperty("placements") List<Placement> placements) {
    }
}
