import unittest
import json
import tempfile
from dataclasses import replace, asdict
from math import pi, cos, sin
from pathlib import Path
from src.app.config import load_config
from src.app.inspection_service import InspectionService
from src.contracts.detections import DetectionFrame, OBBDetection
from src.contracts.inspection import Status
from src.geometry.mother_frame import mother_pose
from src.geometry.roi_builder import build_geometry
from src.geometry.spatial import rectangle, area, intersection, contains
from src.process.recipe import load_recipe, Recipe, Placement
from scripts.demo_data import mother, components
from scripts.replay_detections import replay
from src.vision.detection_adapter import from_ultralytics
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT/"config/mvp.json")
        self.config["registration"] = {"enabled": False}  # original flow; see test_registered_flow.py
        self.recipe = load_recipe(ROOT/"config/recipes/recipe_1.json")
        self.service = InspectionService(self.config, self.recipe)
        self.time = -100
        self.frame_id = -1
        self.prepare()

    def prepare(self):
        for _ in range(11):
            self.tick(self.correct())

    def tick(self, detections, delta=100):
        self.time += delta
        self.frame_id += 1
        return self.service.update(DetectionFrame(self.frame_id, self.time, tuple(detections)))

    def stable(self, detections):
        snapshots = [self.tick(detections) for _ in range(5)]
        return snapshots[-1]

    def correct(self):
        return [mother()]+components(self.recipe, self.config)

    def test_all_recipes_pass(self):
        for name in ("recipe_1", "recipe_2", "recipe_3"):
            self.recipe = load_recipe(ROOT/f"config/recipes/{name}.json")
            self.service.reset(self.recipe)
            self.prepare()
            result = self.stable(self.correct())
            self.assertEqual(result.status, Status.PASS)
            self.assertTrue(result.stable)

    def test_no_single_frame_pass(self):
        result = self.tick(self.correct())
        self.assertEqual(result.status, Status.HOLD)
        self.assertEqual(result.candidate.status, Status.PASS)
        self.assertFalse(result.stable)

    def test_empty_is_in_progress_not_ng(self):
        self.assertEqual(self.stable([mother()]).status, Status.IN_PROGRESS)

    def test_free_order(self):
        parts = components(self.recipe, self.config)
        self.assertEqual(self.stable([mother()]+parts[2:]).status, Status.IN_PROGRESS)
        self.assertEqual(self.stable([mother()]+list(reversed(parts))).status, Status.PASS)

    def test_wrong_bolt(self):
        ds = self.correct()
        ds[1] = replace(ds[1], class_name="bolt_2")
        result = self.stable(ds)
        self.assertEqual(result.status, Status.NG)
        self.assertIn("WRONG_BOLT", [i.code for i in result.candidate.issues])

    def test_wrong_part_uses_observed_type_roi(self):
        alternate = Recipe("alternate", (Placement(1, "bolt_1", "part_3hole"),))
        ds = self.correct()
        ds[2] = components(alternate, self.config)[1]
        result = self.stable(ds)
        self.assertEqual(result.status, Status.NG)
        self.assertIn("WRONG_PART", [i.code for i in result.candidate.issues])

    def test_extra_h5_and_recovery(self):
        self.stable(self.correct())
        extra = OBBDetection("extra", "bolt_1", .99, (1000,700), 80,80,0)
        self.assertEqual(self.stable(self.correct()+[extra]).status, Status.NG)
        self.assertEqual(self.stable(self.correct()).status, Status.PASS)

    def test_extra_part_h5(self):
        extra = OBBDetection("extra", "part_2hole", .99, (1000,520), 500,180,pi/2)
        self.assertEqual(self.stable(self.correct()+[extra]).status, Status.NG)

    def test_duplicate_slot_ng(self):
        ds = self.correct()
        self.assertEqual(self.stable(ds+[replace(ds[1], detection_id="duplicate")]).status, Status.NG)

    def test_spare_far_away_ignored(self):
        extra = OBBDetection("spare", "bolt_1", .99, (1600,700),80,80,0)
        self.assertEqual(self.stable(self.correct()+[extra]).status, Status.PASS)

    def test_unassigned_component_on_mother_holds(self):
        extra = OBBDetection("extra", "bolt_1", .99, (700,700),40,40,0)
        self.assertEqual(self.stable(self.correct()+[extra]).status, Status.HOLD)

    def test_mother_loss_invalidates_pass(self):
        self.stable(self.correct())
        result = self.tick([])
        self.assertEqual(result.status, Status.HOLD)
        self.assertIsNone(result.confirmed)
        self.assertFalse(self.tick(self.correct()).stable)

    def test_short_component_miss_keeps_confirmed(self):
        self.stable(self.correct())
        result = self.tick(self.correct()[:-1])
        self.assertEqual(result.status, Status.PASS)
        self.assertFalse(result.stable)
        self.assertEqual(result.candidate.status, Status.IN_PROGRESS)

    def test_removal_after_pass(self):
        self.stable(self.correct())
        self.assertEqual(self.stable([mother()]).status, Status.IN_PROGRESS)

    def test_frame_gap_does_not_confirm(self):
        self.tick(self.correct())
        result = self.tick(self.correct(), delta=1000)
        self.assertEqual(result.status, Status.HOLD)
        self.assertFalse(result.stable)

    def test_out_of_order_holds(self):
        self.stable(self.correct())
        result = self.service.update(DetectionFrame(0, 0, tuple(self.correct())))
        self.assertEqual(result.status, Status.HOLD)

    def test_multiple_mothers(self):
        self.assertEqual(self.stable(self.correct()+[replace(mother(), detection_id="other")]).status, Status.HOLD)

    def test_no_duplicate_pass_events(self):
        result = self.stable(self.correct())
        self.assertEqual(len(result.events), 1)
        self.assertEqual(self.tick(self.correct()).events, ())

    def test_recipe_reset_clears_pass(self):
        self.stable(self.correct())
        self.service.reset(load_recipe(ROOT/"config/recipes/recipe_3.json"))
        self.assertEqual(self.tick(self.correct()).status, Status.HOLD)

    def test_screen_numbering_and_obb_axis_swap(self):
        for angle, w, h in ((0,1000,160),(pi,1000,160),(pi/2,160,1000)):
            ds = replace(mother(), angle_rad=angle, width=w, height=h)
            geo = build_geometry(mother_pose(ds, self.config), self.config)
            self.assertAlmostEqual(geo["holes"][1][0],200)
            self.assertAlmostEqual(geo["holes"][5][0],1000)

    def test_translation_scale_and_upward_roi(self):
        ds = replace(mother(), center_xy=(300,350), width=500, height=80, angle_rad=10*pi/180)
        geo = build_geometry(mother_pose(ds,self.config),self.config)
        self.assertLess(geo["holes"][1][0], geo["holes"][5][0])
        roi = geo["part_rois"][3]["part_2hole"]
        angle = ds.angle_rad
        self.assertAlmostEqual(roi[1][0]-roi[0][0],90*cos(angle))
        self.assertAlmostEqual(roi[1][1]-roi[0][1],90*sin(angle))
        center = tuple(sum(p[k] for p in roi)/4 for k in (0,1))
        offset = self.config["part_rois"]["part_2hole"]["offset_ratio"]*500
        self.assertAlmostEqual(center[0],300+offset*sin(angle))
        self.assertAlmostEqual(center[1],350-offset*cos(angle))
        self.assertLess(sum(p[1] for p in roi)/4,geo["holes"][3][1])

    def test_angle_limit(self):
        ds = replace(mother(), angle_rad=16*pi/180)
        self.assertEqual(self.stable([ds]).status, Status.HOLD)

    def test_rotated_complete_assembly_passes(self):
        for theta in (-14*pi/180, 14*pi/180):
            self.service.reset()
            self.prepare()
            rotated = []
            for d in self.correct():
                x,y = d.center_xy[0]-600,d.center_xy[1]-700
                rotated.append(replace(d,center_xy=(600+x*cos(theta)-y*sin(theta),
                                                    700+x*sin(theta)+y*cos(theta)),
                                       angle_rad=d.angle_rad+theta))
            result = self.stable(rotated)
            self.assertEqual(result.status,Status.PASS)
            for slots in result.observed.values():
                for part in slots["part"]:
                    self.assertAlmostEqual(part["overlap"],1.0)

    def test_part_orientation_is_mother_relative(self):
        self.config["part_max_angle_deg"] = 5
        theta = 14*pi/180
        ds = []
        for d in self.correct():
            x,y = d.center_xy[0]-600,d.center_xy[1]-700
            ds.append(replace(d,center_xy=(600+x*cos(theta)-y*sin(theta),
                                          700+x*sin(theta)+y*cos(theta)),angle_rad=d.angle_rad+theta))
        self.assertEqual(self.stable(ds).status,Status.PASS)
        ds[2] = replace(ds[2],angle_rad=pi/2)
        result = self.stable(ds)
        self.assertEqual(result.status,Status.NG)
        self.assertIn("PART_ORIENTATION_ERROR",[i.code for i in result.candidate.issues])

    def test_polygon_intersection(self):
        a = rectangle((0,0),2,2)
        b = rectangle((1,0),2,2)
        self.assertAlmostEqual(area(intersection(a,b)),2)
        self.assertAlmostEqual(area(intersection(a,a)),4)
        self.assertEqual(area(intersection(a,rectangle((5,5),2,2))),0)
        self.assertTrue(contains(a,(1,1)))

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            replace(mother(),width=0)
        with self.assertRaises(ValueError):
            replace(mother(),angle_rad=float("nan"))
        with self.assertRaises(ValueError):
            DetectionFrame(0,0,(mother(),mother()))
        with self.assertRaises(ValueError):
            Recipe("bad",(Placement(5,"bolt_1","part_2hole"),))

    def test_invalid_input_holds(self):
        self.stable(self.correct())
        result = self.service.update(DetectionFrame(10,500,tuple(self.correct()),False))
        self.assertEqual(result.status, Status.HOLD)

    def test_tilted_part_is_ng(self):
        ds = self.correct()
        ds[2] = replace(ds[2], angle_rad=65*pi/180)
        result = self.stable(ds)
        self.assertEqual(result.status, Status.NG)
        self.assertIn("PART_ORIENTATION_ERROR",[i.code for i in result.candidate.issues])

    def test_overlapping_hole_rois_hold(self):
        self.config["bolt_half_width_ratio"] = .21
        result = self.stable(self.correct())
        self.assertEqual(result.status, Status.HOLD)

    def test_json_replay_roundtrip(self):
        frame = DetectionFrame(self.frame_id+1,self.time+100,tuple(self.correct()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"frames.jsonl"
            path.write_text(json.dumps(asdict(frame))+"\n",encoding="utf-8")
            result = list(replay(path))
            self.assertEqual(result,[frame])
            snapshot = self.service.update(result[0])
            encoded = json.loads(json.dumps(asdict(snapshot)))
            self.assertEqual(encoded["candidate"]["status"],"PASS")

    def test_adapter_contract_without_model(self):
        class Tensor:
            def __init__(self, data):
                self.data = data
            def cpu(self):
                return self
            def tolist(self):
                return self.data
        result = SimpleNamespace(obb=SimpleNamespace(xywhr=Tensor([[600,700,1000,160,0]]),
                                 cls=Tensor([0]),conf=Tensor([.99])),names={0:"mother_part"})
        frame = from_ultralytics(result,5,1000)
        self.assertEqual(frame.detections[0].center_xy,(600,700))
        self.assertEqual(frame.timestamp_ms,1000)
        result.names = {0:"나무_5구멍"}
        mapped = from_ultralytics(result,6,1100,{"나무_5구멍":"mother_part"})
        self.assertEqual(mapped.detections[0].class_name,"mother_part")


if __name__ == "__main__":
    unittest.main()
