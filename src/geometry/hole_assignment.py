"""Component -> Hole assignment for a registered (locked) Mother.

Lenient but never confuses neighbouring holes:

  * Each component is projected on the Mother long axis and measured in units
    of the hole spacing (``step``). The nearest hole wins if the component is
    within ``accept_ratio`` (0.4) of a step from it.
  * Between two holes there is a boundary zone (0.4 .. 0.6 of a step) where no
    guess is made; the component is reported as ambiguous ("position unclear").
  * Sticky: a component that was on hole j in the previous frame stays on j
    until it is clearly (``switch_ratio``, 0.3 of a step) at another hole, so
    small wobbles near the boundary do not flip the assignment.
  * Perpendicular tolerance is wide (bolts ``bolt_perp_ratio`` x Mother height).
  * Parts use the lower end (towards the Mother) as their anchor. A part lying
    across the Mother (more than ``part_assign_max_angle_deg`` from vertical)
    is being moved, not assembled -> ambiguous instead of a wrong assembly.

Components that do not touch the Mother body are ignored (spares on the table).
Output format is the same as ``association.associate`` so ``evaluator`` is
unchanged.
"""
from math import cos, sin, pi, degrees

from .mother_frame import major_axis
from .spatial import rectangle, area, intersection

DEFAULTS = {
    "accept_ratio": 0.40,             # x hole spacing, around each hole
    "switch_ratio": 0.30,             # sticky: must be this close to another hole to move there
    "sticky_match_ratio": 0.35,       # previous-frame match radius (x spacing)
    "bolt_perp_ratio": 0.80,          # x Mother height, across the long axis
    "part_perp_ratio": 1.00,          # anchor offset across the long axis
    "part_assign_max_angle_deg": 45,  # beyond this a part is "being moved"
    "end_margin_ratio": 0.60,         # beyond H1/H5 by more than this -> not on a hole
}


def assignment_config(config):
    merged = dict(DEFAULTS)
    merged.update(config.get("assignment", {}))
    return merged


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1]


class HoleAssigner:
    def __init__(self, config):
        self.config = config
        self.cfg = assignment_config(config)
        self.previous = []          # [(class_name, t_in_steps, hole)] from the last frame

    def reset(self):
        self.previous = []

    def _frame(self, geometry):
        pose = geometry["pose"]
        u, v, c = pose["u"], pose["v"], pose["center"]
        holes = geometry["holes"]
        ids = sorted(holes)
        ts = [_dot((holes[h][0]-c[0], holes[h][1]-c[1]), u) for h in ids]
        step = (ts[-1]-ts[0])/(len(ts)-1) if len(ts) > 1 else pose["width"]*0.2
        return pose, u, v, c, ids, ts, abs(step)

    def _nearest(self, t, ids, ts, step, class_name):
        units = [(t-ti)/step for ti in ts]
        order = sorted(range(len(ids)), key=lambda i: abs(units[i]))
        best = order[0]
        distance = abs(units[best])
        t_steps = (t-ts[0])/step
        # Sticky: same class, almost same place as last frame -> keep its hole
        # unless it is now clearly at another hole.
        for prev_class, prev_t, prev_hole in self.previous:
            if prev_class == class_name and abs(prev_t-t_steps) <= self.cfg["sticky_match_ratio"]:
                prev_index = ids.index(prev_hole) if prev_hole in ids else None
                if prev_index is not None and prev_index != best and distance > self.cfg["switch_ratio"] \
                        and abs(units[prev_index]) <= 1-self.cfg["switch_ratio"]:
                    return ids[prev_index], abs(units[prev_index]), t_steps
                break
        if distance <= self.cfg["accept_ratio"]:
            return ids[best], distance, t_steps
        return None, distance, t_steps

    def assign(self, detections, geometry):
        """-> (observed, ambiguous_ids, ignored_ids)"""
        pose, u, v, c, ids, ts, step = self._frame(geometry)
        observed = {h: {"bolt": [], "part": []} for h in ids}
        ambiguous, ignored, current = [], [], []
        body = rectangle(pose["center"], pose["width"], pose["height"], pose["angle_rad"])
        span_lo, span_hi = ts[0]-self.cfg["end_margin_ratio"]*step, ts[-1]+self.cfg["end_margin_ratio"]*step
        for d in detections:
            if d.class_name == "mother_part":
                continue
            polygon = rectangle(d.center_xy, d.width, d.height, d.angle_rad)
            touches = area(intersection(polygon, body)) > 1e-8
            slot = "bolt" if d.class_name.startswith("bolt_") else "part"
            orientation_ok = True
            if slot == "bolt":
                point = d.center_xy
                perp_limit = self.cfg["bolt_perp_ratio"]*pose["height"]
            else:
                length, _, angle = major_axis(d)
                error = abs((angle-(pose["angle_rad"]+pi/2)+pi/2) % pi-pi/2)
                if degrees(error) > self.cfg["part_assign_max_angle_deg"]:
                    (ambiguous if touches else ignored).append(d.detection_id)
                    continue
                orientation_ok = degrees(error) <= self.config["part_max_angle_deg"]
                direction = (cos(angle), sin(angle))
                if _dot(direction, v) < 0:          # point towards the Mother (Mother-local down)
                    direction = (-direction[0], -direction[1])
                spec = self.config["part_rois"].get(d.class_name)
                fraction = spec["offset_ratio"]/spec["length_ratio"] if spec else 0.35
                point = (d.center_xy[0]+fraction*length*direction[0], d.center_xy[1]+fraction*length*direction[1])
                perp_limit = self.cfg["part_perp_ratio"]*pose["height"]
            rel = (point[0]-c[0], point[1]-c[1])
            t, q = _dot(rel, u), _dot(rel, v)
            hole0 = geometry["holes"][ids[0]]
            q -= _dot((hole0[0]-c[0], hole0[1]-c[1]), v)      # across-axis offset from the hole line
            if not span_lo <= t <= span_hi or abs(q) > perp_limit:
                (ambiguous if touches else ignored).append(d.detection_id)
                continue
            hole, distance, t_steps = self._nearest(t, ids, ts, step, d.class_name)
            if hole is None:                                # boundary zone between two holes
                ambiguous.append(d.detection_id)
                continue
            current.append((d.class_name, t_steps, hole))
            observed[hole][slot].append({"detection_id": d.detection_id, "class_name": d.class_name,
                                         "confidence": d.confidence, "overlap": round(1-distance, 3),
                                         "offset_steps": round(distance, 3), "point": tuple(round(p, 1) for p in point),
                                         "orientation_ok": orientation_ok})
        self.previous = current
        return observed, tuple(sorted(ambiguous)), tuple(sorted(ignored))
