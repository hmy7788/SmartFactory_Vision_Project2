"""scripts/check_recipes 의 판정 매트릭스가 세 레시피 전부에서 통과해야 한다.
표를 보려면:  python -m scripts.check_recipes
"""
import unittest
from pathlib import Path

from src.app.config import load_config
from scripts.check_recipes import run

ROOT = Path(__file__).resolve().parents[1]


class RecipeMatrixTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config/mvp.json")

    def test_recipe_1(self): self.assertTrue(run("recipe_1", self.config, verbose=False))
    def test_recipe_2(self): self.assertTrue(run("recipe_2", self.config, verbose=False))
    def test_recipe_3(self): self.assertTrue(run("recipe_3", self.config, verbose=False))


if __name__ == "__main__":
    unittest.main()
