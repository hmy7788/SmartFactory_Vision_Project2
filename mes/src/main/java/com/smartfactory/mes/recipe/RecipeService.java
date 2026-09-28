package com.smartfactory.mes.recipe;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartfactory.mes.common.ApiException;
import com.smartfactory.mes.message.Placement;
import com.smartfactory.mes.message.RecipePayload;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RecipeService {

    private static final Set<String> BOLTS = Set.of("bolt_1", "bolt_2");
    private static final Set<String> PARTS = Set.of("part_2hole", "part_3hole");
    private static final TypeReference<List<Placement>> PLACEMENTS = new TypeReference<>() { };

    private final RecipeRepository repo;
    private final ObjectMapper json;

    public RecipeService(RecipeRepository repo, ObjectMapper json) {
        this.repo = repo;
        this.json = json;
    }

    /** 같은 recipe_id 가 있으면 버전 +1 로 새로 만든다 (이전 버전은 그대로 남음). */
    @Transactional
    public Recipe create(String recipeId, List<Placement> placements) {
        validate(recipeId, placements);
        int next = repo.findTopByRecipeIdOrderByVersionDesc(recipeId).map(r -> r.getVersion() + 1).orElse(1);
        try {
            return repo.save(new Recipe(recipeId, next, json.writeValueAsString(placements)));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    /** version 이 null 이면 최신 버전. */
    @Transactional(readOnly = true)
    public Recipe resolve(String recipeId, Integer version) {
        return (version == null ? repo.findTopByRecipeIdOrderByVersionDesc(recipeId)
                : repo.findByRecipeIdAndVersion(recipeId, version))
                .orElseThrow(() -> ApiException.notFound("레시피 없음: " + recipeId + (version == null ? "" : " v" + version)));
    }

    @Transactional(readOnly = true)
    public List<Recipe> all() {
        return repo.findAllByOrderByRecipeIdAscVersionDesc();
    }

    public List<Placement> placements(Recipe recipe) {
        try {
            return json.readValue(recipe.getPlacementsJson(), PLACEMENTS);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("레시피 " + recipe.getRecipeId() + " 의 placements_json 이 깨짐", e);
        }
    }

    public RecipePayload payload(Recipe recipe) {
        return new RecipePayload(recipe.getRecipeId(), recipe.getVersion(), placements(recipe));
    }

    /** 검사대(src/process/recipe.py) 와 같은 규칙. 여기서 막아야 검사대가 REJECTED 를 보내는 일이 없다. */
    public static void validate(String recipeId, List<Placement> placements) {
        if (recipeId == null || recipeId.isBlank()) {
            throw ApiException.badRequest("recipe_id 가 비었습니다");
        }
        if (placements == null || placements.isEmpty()) {
            throw ApiException.badRequest("placements 가 비었습니다");
        }
        Set<Integer> holes = new HashSet<>();
        for (Placement p : placements) {
            if (p.motherHole() < 1 || p.motherHole() > 4) {
                throw ApiException.badRequest("H1~H4 만 지정할 수 있습니다 (H5 는 항상 비움): H" + p.motherHole());
            }
            if (!holes.add(p.motherHole())) {
                throw ApiException.badRequest("같은 자리를 두 번 쓸 수 없습니다: H" + p.motherHole());
            }
            if (!BOLTS.contains(p.bolt()) || !PARTS.contains(p.part())) {
                throw ApiException.badRequest("모르는 부품: " + p.bolt() + " / " + p.part());
            }
        }
    }
}
