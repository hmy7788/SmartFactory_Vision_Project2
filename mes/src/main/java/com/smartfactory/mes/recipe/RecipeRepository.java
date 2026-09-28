package com.smartfactory.mes.recipe;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

public interface RecipeRepository extends JpaRepository<Recipe, Long> {

    Optional<Recipe> findTopByRecipeIdOrderByVersionDesc(String recipeId);

    Optional<Recipe> findByRecipeIdAndVersion(String recipeId, int version);

    List<Recipe> findAllByOrderByRecipeIdAscVersionDesc();
}
