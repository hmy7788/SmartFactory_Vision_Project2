from math import pi
from dataclasses import replace
from src.contracts.detections import DetectionFrame, OBBDetection


def mother():
    return OBBDetection("mother", "mother_part", 0.99, (600, 700), 1000, 160, 0)


def components(recipe, config):
    result = []
    for p in recipe.placements:
        x = 600 + config["hole_alphas"][p.mother_hole-1]*1000
        result.append(OBBDetection(f"b{p.mother_hole}", p.bolt, 0.99, (x, 700), 80, 80, 0))
        roi = config["part_rois"][p.part]
        result.append(OBBDetection(f"p{p.mother_hole}", p.part, 0.99,
                                   (x, 700-roi["offset_ratio"]*1000),
                                   roi["length_ratio"]*1000, roi["width_ratio"]*1000, pi/2))
    return result


def demo_frames(recipe, config):
    correct = components(recipe, config)
    extra = OBBDetection("extra_h5", "bolt_1", 0.99, (1000, 700), 80, 80, 0)
    # Spread material detections away from Mother: inventory does not use ROIs.
    ready = [replace(d, center_xy=(150+i*220,150)) for i,d in enumerate(correct)]
    # ([],12): Mother alone and hands off for Mother registration (1 s).
    stages = [([],6), (ready+[extra],12), (ready,12), ([],12),
              (correct,6), (correct+[extra],6), (correct,6), (None,6), (correct,6)]
    frame_id = 0
    for stage, count in stages:
        for _ in range(count):
            yield DetectionFrame(frame_id, frame_id*100, tuple([mother()]+stage) if stage is not None else ())
            frame_id += 1
