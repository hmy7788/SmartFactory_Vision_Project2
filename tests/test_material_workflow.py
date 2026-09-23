import unittest
from pathlib import Path
from dataclasses import replace
from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.process.recipe import load_recipe
from src.process.materials import evaluate_materials
from src.contracts.inspection import Phase, Status
from src.contracts.detections import DetectionFrame
from scripts.demo_data import mother, components

ROOT = Path(__file__).resolve().parents[1]


class MaterialWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        self.recipe = load_recipe(ROOT/"config/recipes/recipe_1.json")
        self.service = InspectionService(self.config,self.recipe)
        self.clock = -100
        self.index = -1

    def inventory(self):
        return [mother()]+[replace(d,center_xy=(100+i*200,100))
                           for i,d in enumerate(components(self.recipe,self.config))]

    def tick(self, ds, gap=100, valid=True):
        self.clock += gap
        self.index += 1
        return self.service.update(DetectionFrame(self.index,self.clock,tuple(ds),valid))

    def feed(self, ds, count=11):
        return [self.tick(ds) for _ in range(count)]

    def test_exact_all_recipes(self):
        for name in ("recipe_1","recipe_2","recipe_3"):
            self.recipe = load_recipe(ROOT/f"config/recipes/{name}.json")
            self.service.reset(self.recipe)
            results = self.feed(self.inventory())
            self.assertTrue(all(r.phase == Phase.CHECK_MATERIALS for r in results[:-1]))
            last = results[-1]
            self.assertEqual(last.phase,Phase.ASSEMBLING)
            self.assertEqual(last.evaluated_phase,Phase.CHECK_MATERIALS)
            self.assertEqual(last.candidate.status,Status.READY)
            self.assertIsNone(last.confirmed)
            self.assertEqual(last.events[0]["event_type"],"ASSEMBLY_STARTED")

    def test_recipe2_counts_two_each(self):
        recipe = load_recipe(ROOT/"config/recipes/recipe_2.json")
        _,counts = evaluate_materials(recipe,())
        self.assertEqual(counts["expected"],{"mother_part":1,"bolt_1":2,"bolt_2":0,"part_2hole":2,"part_3hole":0})

    def test_missing_stays_preparing(self):
        result = self.feed(self.inventory()[:-1])[-1]
        self.assertEqual(result.phase,Phase.CHECK_MATERIALS)
        self.assertEqual(result.status,Status.IN_PROGRESS)

    def test_excess_blocks_then_correction_starts(self):
        ds = self.inventory()
        extra = replace(ds[1],detection_id="extra",center_xy=(2000,2000))
        result = self.feed(ds+[extra])[-1]
        self.assertEqual(result.phase,Phase.CHECK_MATERIALS)
        self.assertEqual(result.status,Status.NG)
        self.assertIn("MATERIAL_EXCESS",[i.code for i in result.candidate.issues])
        self.assertEqual(self.feed(ds)[-1].phase,Phase.ASSEMBLING)

    def test_wrong_type_same_total_blocks(self):
        self.recipe = load_recipe(ROOT/"config/recipes/recipe_2.json")
        self.service.reset(self.recipe)
        ds = self.inventory()
        ds[1] = replace(ds[1],class_name="bolt_2")
        result = self.feed(ds)[-1]
        self.assertEqual(result.phase,Phase.CHECK_MATERIALS)
        self.assertEqual(result.status,Status.NG)
        self.assertIn("MATERIAL_UNEXPECTED",[i.code for i in result.candidate.issues])

    def test_multiple_mothers_is_excess_in_preparation(self):
        result = self.feed(self.inventory()+[replace(mother(),detection_id="second")])[-1]
        self.assertEqual(result.phase,Phase.CHECK_MATERIALS)
        self.assertEqual(result.status,Status.NG)

    def test_one_frame_and_interruption_not_ready(self):
        self.feed(self.inventory(),10)
        self.tick(self.inventory()[:-1])
        self.assertEqual(self.feed(self.inventory(),10)[-1].phase,Phase.CHECK_MATERIALS)
        self.assertEqual(self.tick(self.inventory()).phase,Phase.ASSEMBLING)

    def test_invalid_and_gap_reset_evidence(self):
        for invalid in (False,True):
            self.service.reset()
            self.feed(self.inventory(),10)
            result = self.tick(self.inventory(),gap=100 if invalid else 1000,valid=not invalid)
            self.assertEqual(result.candidate.status,Status.HOLD)
            self.assertEqual(self.feed(self.inventory(),10)[-1].phase,Phase.CHECK_MATERIALS)

    def test_no_recount_after_start_and_loss(self):
        results = self.feed(self.inventory())
        result = self.tick([])
        self.assertEqual(result.phase,Phase.ASSEMBLING)
        self.assertEqual(result.status,Status.HOLD)
        self.assertEqual(result.materials,{})
        result = self.feed([mother()],5)[-1]
        self.assertEqual(result.phase,Phase.ASSEMBLING)
        self.assertEqual(result.status,Status.IN_PROGRESS)
        correct = [mother()]+components(self.recipe,self.config)
        # A loose extra is no longer counted after the one-way gate.
        extra = replace(correct[1],detection_id="loose",center_xy=(2000,2000))
        result = self.feed(correct+[extra],5)[-1]
        self.assertEqual(result.status,Status.PASS)
        self.assertEqual(result.materials,{})
        self.assertFalse(any(e["event_type"]=="ASSEMBLY_STARTED" for e in result.events))

    def test_assembled_extra_still_ng(self):
        self.feed(self.inventory())
        ds = [mother()]+components(self.recipe,self.config)
        extra = replace(ds[1],detection_id="h5",center_xy=(1000,700))
        result = self.feed(ds+[extra],5)[-1]
        self.assertEqual(result.phase,Phase.ASSEMBLING)
        self.assertEqual(result.status,Status.NG)

    def test_reset_requires_materials_again(self):
        self.feed(self.inventory())
        self.service.reset()
        self.assertEqual(self.tick([]).phase,Phase.CHECK_MATERIALS)

    def test_preparation_ignores_mother_angle(self):
        ds = self.inventory()
        ds[0] = replace(ds[0],angle_rad=.7)
        self.assertEqual(self.feed(ds)[-1].phase,Phase.ASSEMBLING)
        self.assertEqual(self.tick(ds).candidate.status,Status.HOLD)

    def test_low_confidence_not_counted(self):
        ds = self.inventory()
        ds[1] = replace(ds[1],confidence=.1)
        self.assertEqual(self.feed(ds)[-1].phase,Phase.CHECK_MATERIALS)


if __name__ == "__main__":
    unittest.main()
