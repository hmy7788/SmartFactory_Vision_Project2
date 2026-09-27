from .spatial import rectangle


def build_geometry(pose, config):
    """Mother pose → hole points, bolt ROIs, part ROIs.

    Part ROIs come in two sets: `part_rois` on the Mother-local up side (-v: screen up when the
    Mother is horizontal) and `part_rois_down` mirrored to the +v side. A part is attached with a
    bolt through a hole, so it may extend to either side; `associate` picks the set by which side
    the part's centre lies on. Same shape, same hole, only the direction differs.
    """
    c, u, v = pose["center"], pose["u"], pose["v"]
    width, height = pose["width"], pose["height"]
    holes, bolts, parts, parts_down = {}, {}, {}, {}
    for hole, alpha in enumerate(config["hole_alphas"], 1):
        point = tuple(c[k] + alpha*width*u[k] + config["hole_beta"]*height*v[k] for k in (0, 1))
        holes[hole] = point
        bolts[hole] = rectangle(point, 2*config["bolt_half_width_ratio"]*width,
                                2*config["bolt_half_height_ratio"]*height, pose["angle_rad"])
        parts[hole], parts_down[hole] = {}, {}
        for name, spec in config["part_rois"].items():
            for target, sign in ((parts, -1), (parts_down, +1)):
                center = tuple(point[k] + sign*spec["offset_ratio"]*width*v[k] for k in (0, 1))
                target[hole][name] = rectangle(center, spec["width_ratio"]*width,
                                               spec["length_ratio"]*width, pose["angle_rad"])
    return {"pose": pose, "holes": holes, "bolt_rois": bolts, "part_rois": parts, "part_rois_down": parts_down}


def part_side(detection, pose) -> int:
    """-1 = the part's centre is on the Mother-local up side (-v), +1 = down side (+v)."""
    v = pose["v"]
    rel = sum((detection.center_xy[k] - pose["center"][k]) * v[k] for k in (0, 1))
    return 1 if rel > 0 else -1
