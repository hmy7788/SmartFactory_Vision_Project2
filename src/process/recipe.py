import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Placement:
    mother_hole: int
    bolt: str
    part: str


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    placements: tuple[Placement, ...]

    def __post_init__(self):
        if not self.recipe_id or not self.placements:
            raise ValueError("Recipe identity/placements required")
        holes = [p.mother_hole for p in self.placements]
        if len(holes) != len(set(holes)):
            raise ValueError("Duplicate recipe Hole")
        for p in self.placements:
            if type(p.mother_hole) is not int or p.mother_hole not in range(1, 5):
                raise ValueError("Only H1-H4 may be required; H5 is prohibited")
            if p.bolt not in {"bolt_1", "bolt_2"} or p.part not in {"part_2hole", "part_3hole"}:
                raise ValueError("Invalid recipe component")


def load_recipe(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Recipe(data["recipe_id"], tuple(Placement(**p) for p in data["placements"]))
