from math import cos, sin, degrees, hypot, pi
from .mother_frame import major_axis
from .spatial import contains, overlap, rectangle, area, intersection


def associate(detections, geometry, config):
    """No recipe-based candidate filtering. Multiple matches conservatively hold."""
    observed = {i: {"bolt": [], "part": []} for i in range(1, 6)}
    ambiguous, ignored = [], []
    # Opt-in (config "allow_parts_below"): tracks which Mother-local side each matched part
    # actually came from, so a physically-impossible mix (one part above, another below, in
    # the same rigid planar assembly) can be caught below instead of silently passing.
    part_sides = {}
    width = geometry["pose"]["width"]
    for d in detections:
        if d.class_name == "mother_part":
            continue
        slot = "bolt" if d.class_name.startswith("bolt_") else "part"
        side_used = None
        if slot == "bolt":
            matches = [h for h, roi in geometry["bolt_rois"].items() if contains(roi, d.center_xy)]
            scores = {h: 1.0 for h in matches}
        else:
            # Part's Mother-side end must be near the Mother anchor. Overlap alone
            # cannot distinguish a loose component far from the Mother. The part
            # may hang on either Mother-local side, so both sides are evaluated.
            length, _, angle = major_axis(d)
            spec = config["part_rois"][d.class_name]
            fraction = spec["offset_ratio"] / spec["length_ratio"]
            mother_down = geometry["pose"]["v"]

            def evaluate_side(rois_key, mother_end):
                """mother_end=+1: the end toward Mother-local down touches the Mother (part above)."""
                side_scores = {h: overlap(d, rois[d.class_name]) for h, rois in geometry[rois_key].items()}
                direction = (cos(angle), sin(angle))
                if mother_end*sum(direction[k]*mother_down[k] for k in (0, 1)) < 0:
                    direction = (-direction[0], -direction[1])
                anchor = tuple(d.center_xy[k] + fraction*length*direction[k] for k in (0, 1))
                side_near = [h for h, p in geometry["holes"].items()
                             if hypot(anchor[0]-p[0], anchor[1]-p[1]) <= config["part_anchor_tolerance_ratio"]*width]
                side_matches = [h for h in side_near if side_scores[h] >= config["part_overlap_threshold"]]
                return side_scores, side_near, side_matches

            above = evaluate_side("part_rois", +1)
            # Opt-in (config "allow_parts_below"): default keeps the original up-only behavior.
            below = evaluate_side("part_rois_down", -1) if config.get("allow_parts_below") else (None, [], [])
            if above[2] and below[2]:
                # Physically impossible for one part; hold rather than guess.
                ambiguous.append(d.detection_id)
                continue
            side_used = "below" if below[2] else "above"
            scores, near, matches = below if below[2] else above
            if not matches and (above[1] or below[1]):
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
            if slot == "part" and config.get("allow_parts_below"):
                part_sides[d.detection_id] = side_used

    if len(set(part_sides.values())) > 1:
        # A single rigid, planar assembly can't have some parts above Mother and others
        # below at the same time -- hold those parts rather than accept the impossible mix.
        mixed_ids = set(part_sides)
        ambiguous.extend(mixed_ids)
        for slots in observed.values():
            slots["part"] = [p for p in slots["part"] if p["detection_id"] not in mixed_ids]

    return observed, tuple(sorted(ambiguous)), tuple(sorted(ignored))
