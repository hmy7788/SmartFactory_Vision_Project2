package com.smartfactory.mes.recipe;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;

/**
 * 레시피(기준정보). 고치지 않고 버전을 올린다 — 이미 만든 제품이 "어떤 기준으로 검사됐나" 를 잃지 않으려고.
 */
@Entity
@Table(name = "recipe", uniqueConstraints = @UniqueConstraint(columnNames = {"recipe_id", "recipe_version"}))
public class Recipe {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "recipe_id", nullable = false, length = 50)
    private String recipeId;

    @Column(name = "recipe_version", nullable = false)
    private int version;

    @Column(name = "placements_json", nullable = false, length = 2000)
    private String placementsJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected Recipe() {
    }

    public Recipe(String recipeId, int version, String placementsJson) {
        this.recipeId = recipeId;
        this.version = version;
        this.placementsJson = placementsJson;
        this.createdAt = Instant.now();
    }

    public Long getId() {
        return id;
    }

    public String getRecipeId() {
        return recipeId;
    }

    public int getVersion() {
        return version;
    }

    public String getPlacementsJson() {
        return placementsJson;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
