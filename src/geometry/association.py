from math import cos, sin, degrees, hypot, pi
from .mother_frame import major_axis
from .spatial import contains, overlap, rectangle, area, intersection


def associate(detections, geometry, config):
    """No recipe-based candidate filtering. Multiple matches conservatively hold."""
    observed = {i: {"bolt": [], "part": []} for i in range(1, 6)}
    ambiguous, ignored = [], []
    width = geometry["pose"]["width"]
    for d in detections:
        if d.class_name == "mother_part":
            continue
        slot = "bolt" if d.class_name.startswith("bolt_") else "part"
        if slot == "bolt":
            matches = [h for h, roi in geometry["bolt_rois"].items() if contains(roi, d.center_xy)]
            scores = {h: 1.0 for h in matches}
        else:
            scores = {h: overlap(d, rois[d.class_name]) for h, rois in geometry["part_rois"].items()}
            # Part's lower end must be near the Mother anchor. Overlap alone
            # cannot distinguish a loose component high above the Mother.
            length, _, angle = major_axis(d)
            direction = (cos(angle), sin(angle))
            mother_down = geometry["pose"]["v"]
            if sum(direction[k]*mother_down[k] for k in (0, 1)) < 0:
                direction = (-direction[0], -direction[1])
            spec = config["part_rois"][d.class_name]
            fraction = spec["offset_ratio"] / spec["length_ratio"]
            estimated_anchor = tuple(d.center_xy[k] + fraction*length*direction[k] for k in (0, 1))
            near = [h for h, p in geometry["holes"].items()
                    if hypot(estimated_anchor[0]-p[0], estimated_anchor[1]-p[1]) <= config["part_anchor_tolerance_ratio"]*width]
            matches = [h for h in near if scores[h] >= config["part_overlap_threshold"]]
            if not matches and near:
                ambiguous.append(d.detection_id)
                continue
        if len(matches) > 1:
            ambiguous.append(d.detection_id)
        elif not matches:
            pose = geometry["pose"]
            body = rectangle(pose["center"], pose["width"], pose["height"], pose["angle_rad"])
            polygon = rectangle(d.center_xy, d.width, d.height, d.angle_rad)
            if area(intersection(polygon, body)) > 1e-8:
                # A component at the Mother with no reliable anchor must never
                # disappear from inspection simply because its ROI score failed.
                ambiguous.append(d.detection_id)
            else:
                ignored.append(d.detection_id)
        else:
            h = matches[0]
            orientation_ok = True
            if slot == "part":
                _, _, angle = major_axis(d)
                expected_angle = geometry["pose"]["angle_rad"] + pi/2
                error = abs((angle-expected_angle+pi/2) % pi-pi/2)
                orientation_ok = degrees(error) <= config["part_max_angle_deg"]
            observed[h][slot].append({"detection_id": d.detection_id, "class_name": d.class_name,
                                      "confidence": d.confidence, "overlap": scores[h],
                                      "orientation_ok": orientation_ok})
    return observed, tuple(sorted(ambiguous)), tuple(sorted(ignored))
