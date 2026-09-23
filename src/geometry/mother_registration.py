"""Mother registration (lock) and movement tracking.

Flow
  1. REGISTER: the worker places only the Mother, top face up, and lets go.
     Each frame a candidate Mother must pass: angle limit, 5:1-like shape,
     nothing lying on top of it, and all five holes visible in an evenly spaced
     line (a 2/3-hole part or a Mother on its 2-hole side face fails here).
     After ``register_stable_ms`` of consistent frames the pose and the
     measured hole positions are locked.
  2. TRACK (during assembly): the locked geometry is used even when hands or
     parts hide the Mother. Only a sustained, full-size Mother detection away
     from the lock moves it (``MOTHER_MOVING`` HOLD until re-locked).

Pure Python: pixel measurement lives in src/vision/hole_detector.py and is
passed in as objects exposing ``holes`` (alpha, beta, visible) and
``visible_count``.
"""
from dataclasses import dataclass
from math import cos, sin, pi, hypot, degrees

from src.contracts.inspection import Issue
from .mother_frame import major_axis
from .roi_builder import build_geometry
from .spatial import rectangle, area, intersection

DEFAULTS = {
    "register_stable_ms": 1000,        # hands-off time before locking
    "register_min_frames": 3,
    "register_max_gap_ms": 1000,       # slower than the 250 ms inspection gap: CPU inference is ok
    "register_max_shift_ratio": 0.02,  # centre jitter allowed while registering (x Mother length)
    "register_max_angle_jitter_deg": 2.0,
    "aspect_range": [3.8, 6.5],        # Mother length/width ~4.3-5.4 (perspective); 2-hole ~3.0. 3-hole fails the 5-hole check
    "hole_min_contrast": 0.45,
    "hole_span_tolerance": 0.15,       # (H5-H1) vs nominal span
    "hole_center_tolerance": 0.08,     # |alpha(H3)|
    "hole_max_abs_beta": 0.25,
    "hole_spacing_cv_max": 0.15,
    "hole_search_ratio": 0.08,
    "crop_margin_ratio": 0.06,
    "clear_overlap_ratio": 0.05,       # component area on Mother that blocks registration
    "move_tolerance_ratio": 0.05,
    "move_angle_deg": 4.0,
    "move_confirm_ms": 1000,
    "reliable_length_ratio": [0.9, 1.1],  # detection length vs locked length
    "lost_hold_ms": 3000,
}


def registration_config(config):
    merged = dict(DEFAULTS)
    merged.update(config.get("registration", {}))
    return merged


def registration_enabled(config):
    return bool(config.get("registration", {}).get("enabled", False))


@dataclass(frozen=True)
class NominalHole:
    hole_id: int
    alpha: float
    beta: float
    visible: bool = True


@dataclass(frozen=True)
class NominalMeasurement:
    """Stand-in when no image is available (JSONL replay, unit tests)."""
    holes: tuple[NominalHole, ...]

    @property
    def visible_count(self):
        return len(self.holes)


def nominal_measurement(config):
    return NominalMeasurement(tuple(NominalHole(i, a, config["hole_beta"])
                                    for i, a in enumerate(config["hole_alphas"], 1)))


def _wrap(angle):
    return (angle + pi) % (2*pi) - pi


@dataclass(frozen=True)
class MotherLock:
    center: tuple[float, float]
    width: float
    height: float
    angle_rad: float                       # u axis points from H1 towards H5
    hole_local: tuple[tuple[float, float], ...]
    locked_at_ms: float

    def pose(self):
        a = self.angle_rad
        return {"center": self.center, "width": self.width, "height": self.height,
                "angle_rad": a, "u": (cos(a), sin(a)), "v": (-sin(a), cos(a))}

    def geometry(self, config):
        geometry = build_geometry(self.pose(), config, self.hole_local)
        geometry["registered"] = True
        return geometry

    def moved_to(self, detection, timestamp_ms):
        length, short, angle = major_axis(detection)
        # Keep H1 identity: choose the axis direction closest to the lock.
        angle = min((angle, angle+pi, angle-pi), key=lambda a: abs(_wrap(a-self.angle_rad)))
        return MotherLock(detection.center_xy, length, short, angle, self.hole_local, timestamp_ms)


@dataclass(frozen=True)
class RegistrationStatus:
    locked: bool
    progress: float                 # 0..1 hands-off stability progress
    issues: tuple[Issue, ...]
    lock: MotherLock | None = None
    mother_id: str | None = None


def _components_on(detection, components, reg):
    width, height, angle = major_axis(detection)
    body = rectangle(detection.center_xy, width, height, angle)
    blocking = []
    for d in components:
        polygon = rectangle(d.center_xy, d.width, d.height, d.angle_rad)
        if area(intersection(polygon, body)) > reg["clear_overlap_ratio"]*d.width*d.height:
            blocking.append(d.class_name)
    return blocking


def check_mother(detection, measurement, components, config):
    """Issues preventing this detection from being registered (empty = OK)."""
    reg = registration_config(config)
    width, height, angle = major_axis(detection)
    issues = []
    if abs(degrees(angle)) > config["max_mother_angle_deg"]:
        issues.append(Issue("MOTHER_ANGLE_OUT_OF_RANGE", observed=f"{degrees(angle):.1f}"))
    aspect = width/height
    if not reg["aspect_range"][0] <= aspect <= reg["aspect_range"][1]:
        issues.append(Issue("MOTHER_SHAPE_MISMATCH", observed=f"{aspect:.2f}"))
    blocking = _components_on(detection, components, reg)
    if blocking:
        issues.append(Issue("MOTHER_NOT_CLEAR", observed=",".join(sorted(blocking))))
    if measurement is None:
        issues.append(Issue("HOLE_MEASUREMENT_UNAVAILABLE"))
        return tuple(sorted(issues))
    if measurement.visible_count < len(config["hole_alphas"]):
        issues.append(Issue("MOTHER_HOLES_NOT_VISIBLE", expected=str(len(config["hole_alphas"])),
                            observed=str(measurement.visible_count)))
        return tuple(sorted(issues))
    holes = measurement.holes
    # Relative layout only: the OBB length/centre may be a few % off, so the
    # holes are checked against each other, not against the nominal ratios.
    alphas = [h.alpha for h in holes]
    gaps = [b-a for a, b in zip(alphas, alphas[1:])]
    mean = sum(gaps)/len(gaps)
    spread = (sum((g-mean)**2 for g in gaps)/len(gaps))**0.5
    span = alphas[-1]-alphas[0]
    nominal_span = config["hole_alphas"][-1]-config["hole_alphas"][0]
    if mean <= 0 or spread/mean > reg["hole_spacing_cv_max"]:
        issues.append(Issue("MOTHER_HOLE_LAYOUT_MISMATCH", observed=f"spacing_cv={spread/max(mean, 1e-9):.2f}"))
    elif abs(span/nominal_span-1) > reg["hole_span_tolerance"]:
        issues.append(Issue("MOTHER_HOLE_LAYOUT_MISMATCH", observed=f"span={span:.2f}"))
    elif abs(alphas[len(alphas)//2]) > reg["hole_center_tolerance"] or \
            max(abs(h.beta) for h in holes) > reg["hole_max_abs_beta"]:
        issues.append(Issue("MOTHER_HOLE_LAYOUT_MISMATCH", observed="off_center"))
    return tuple(sorted(issues))


class MotherRegistrar:
    """Locks the Mother after a hands-off, fully visible period."""

    def __init__(self, config):
        self.config = config
        self.reg = registration_config(config)
        self.reset()

    def reset(self):
        self.since = None
        self.last_ts = None
        self.reference = None
        self.samples = []
        self.lock = None

    def _restart(self):
        self.since, self.reference, self.samples = None, None, []

    def update(self, timestamp_ms, mothers, components, measurements):
        """mothers: mother_part detections; measurements: {detection_id: measurement}."""
        if self.lock is not None:
            return RegistrationStatus(True, 1.0, (), self.lock)
        gap = self.last_ts is not None and timestamp_ms-self.last_ts > self.reg["register_max_gap_ms"]
        self.last_ts = timestamp_ms
        if gap:
            self._restart()
        if not mothers:
            self._restart()
            return RegistrationStatus(False, 0.0, (Issue("MOTHER_NOT_FOUND"),))
        checked = [(m, check_mother(m, measurements.get(m.detection_id), components, self.config)) for m in mothers]
        passing = [m for m, issues in checked if not issues]
        if len(passing) != 1:
            self._restart()
            if passing:
                return RegistrationStatus(False, 0.0, (Issue("MULTIPLE_MOTHERS"),))
            # Report the most plausible Mother (most visible holes) to the worker.
            best = max(checked, key=lambda c: getattr(measurements.get(c[0].detection_id), "visible_count", -1))
            return RegistrationStatus(False, 0.0, best[1], mother_id=best[0].detection_id)
        mother = passing[0]
        width, height, angle = major_axis(mother)
        if self.reference is not None:
            cx, cy, ref_angle, ref_width = self.reference
            moved = hypot(mother.center_xy[0]-cx, mother.center_xy[1]-cy) > self.reg["register_max_shift_ratio"]*ref_width
            turned = abs(degrees(_wrap(angle-ref_angle))) > self.reg["register_max_angle_jitter_deg"]
            if moved or turned:
                self._restart()
        if self.reference is None:
            self.reference = (*mother.center_xy, angle, width)
            self.since = timestamp_ms
        holes = measurements[mother.detection_id].holes
        self.samples.append((mother, tuple((h.alpha, h.beta) for h in holes)))
        elapsed = timestamp_ms-self.since
        progress = min(1.0, elapsed/self.reg["register_stable_ms"])
        if elapsed < self.reg["register_stable_ms"] or len(self.samples) < self.reg["register_min_frames"]:
            return RegistrationStatus(False, progress, (Issue("MOTHER_REGISTERING"),), mother_id=mother.detection_id)
        n = len(self.samples)
        cx = sum(m.center_xy[0] for m, _ in self.samples)/n
        cy = sum(m.center_xy[1] for m, _ in self.samples)/n
        axes = [major_axis(m) for m, _ in self.samples]
        width = sum(a[0] for a in axes)/n
        height = sum(a[1] for a in axes)/n
        angle = sum(_wrap(a[2]-axes[0][2]) for a in axes)/n + axes[0][2]
        hole_local = tuple((sum(s[1][i][0] for s in self.samples)/n, sum(s[1][i][1] for s in self.samples)/n)
                           for i in range(len(self.config["hole_alphas"])))
        self.lock = MotherLock((cx, cy), width, height, angle, hole_local, timestamp_ms)
        return RegistrationStatus(True, 1.0, (), self.lock, mother.detection_id)


class MotherTracker:
    """Keeps the lock during assembly; re-locks only after a sustained move."""

    def __init__(self, lock, config):
        self.config = config
        self.reg = registration_config(config)
        self.lock = lock
        self.pending = None
        self.lost_since = None

    def _reliable(self, detection):
        length = major_axis(detection)[0]
        low, high = self.reg["reliable_length_ratio"]
        return low*self.lock.width <= length <= high*self.lock.width

    def _deviation(self, lock, detection):
        candidate = lock.moved_to(detection, 0)
        shift = hypot(candidate.center[0]-lock.center[0], candidate.center[1]-lock.center[1])/lock.width
        turn = abs(degrees(_wrap(candidate.angle_rad-lock.angle_rad)))
        return shift, turn

    def update(self, timestamp_ms, mothers):
        """Returns (lock, issues, events)."""
        reliable = [m for m in mothers if self._reliable(m)]
        if not reliable:
            # Hidden by hands/parts: trust the lock for a while.
            self.pending = None
            self.lost_since = timestamp_ms if self.lost_since is None else self.lost_since
            if timestamp_ms-self.lost_since > self.reg["lost_hold_ms"] and not mothers:
                return self.lock, (Issue("MOTHER_LOST"),), ()
            return self.lock, (), ()
        self.lost_since = None
        detection = min(reliable, key=lambda m: hypot(m.center_xy[0]-self.lock.center[0],
                                                      m.center_xy[1]-self.lock.center[1]))
        shift, turn = self._deviation(self.lock, detection)
        if shift <= self.reg["move_tolerance_ratio"] and turn <= self.reg["move_angle_deg"]:
            self.pending = None
            return self.lock, (), ()
        candidate = self.lock.moved_to(detection, timestamp_ms)
        if self.pending is not None:
            p_shift, p_turn = self._deviation(self.pending, detection)
            if p_shift > self.reg["move_tolerance_ratio"] or p_turn > self.reg["move_angle_deg"]:
                self.pending = None
        if self.pending is None:
            self.pending = candidate
        if timestamp_ms-self.pending.locked_at_ms < self.reg["move_confirm_ms"]:
            return self.lock, (Issue("MOTHER_MOVING"),), ()
        self.lock, self.pending = candidate, None
        issues = ()
        if abs(degrees(_wrap(self.lock.angle_rad))) > self.config["max_mother_angle_deg"] and \
                abs(degrees(_wrap(self.lock.angle_rad-pi))) > self.config["max_mother_angle_deg"]:
            issues = (Issue("MOTHER_ANGLE_OUT_OF_RANGE"),)
        return self.lock, issues, ({"event_type": "MOTHER_RELOCKED", "timestamp_ms": timestamp_ms},)
