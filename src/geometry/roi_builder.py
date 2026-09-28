from .spatial import rectangle


def build_geometry(pose, config, hole_local=None):
    """hole_local: optional measured (alpha, beta) per Hole from Mother registration.

    Without it the nominal config hole_alphas/hole_beta ratios are used.
    """
    c, u, v = pose["center"], pose["u"], pose["v"]
    width, height = pose["width"], pose["height"]
    holes, bolts, parts = {}, {}, {}
    if hole_local is None:
        hole_local = [(alpha, config["hole_beta"]) for alpha in config["hole_alphas"]]
    for hole, (alpha, beta) in enumerate(hole_local, 1):
        point = tuple(c[k] + alpha*width*u[k] + beta*height*v[k] for k in (0, 1))
        holes[hole] = point
        bolts[hole] = rectangle(point, 2*config["bolt_half_width_ratio"]*width,
                                2*config["bolt_half_height_ratio"]*height, pose["angle_rad"])
        parts[hole] = {}
        for name, spec in config["part_rois"].items():
            # -v is Mother-local up (screen up when Mother is horizontal).
            center = tuple(point[k]-spec["offset_ratio"]*width*v[k] for k in (0, 1))
            parts[hole][name] = rectangle(center, spec["width_ratio"]*width,
                                          spec["length_ratio"]*width, pose["angle_rad"])
    return {"pose": pose, "holes": holes, "bolt_rois": bolts, "part_rois": parts}
