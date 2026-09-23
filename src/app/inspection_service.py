from dataclasses import asdict
from src.contracts.inspection import Candidate, Issue, Snapshot, Status, Phase
from src.geometry.mother_frame import mother_pose
from src.geometry.roi_builder import build_geometry
from src.geometry.association import associate
from src.geometry.mother_registration import (MotherRegistrar, MotherTracker, nominal_measurement,
                                              registration_config, registration_enabled)
from src.process.evaluator import evaluate
from src.process.materials import evaluate_materials
from src.process.occlusion import HoleMemory
from src.process.state_machine import StateMachine

EVENT_TYPES = {
    (Phase.CHECK_MATERIALS, Phase.ASSEMBLING): "ASSEMBLY_STARTED",      # registration disabled
    (Phase.CHECK_MATERIALS, Phase.REGISTER_MOTHER): "MATERIALS_READY",
    (Phase.REGISTER_MOTHER, Phase.ASSEMBLING): "ASSEMBLY_STARTED",
}


class InspectionService:
    """Frame loop core.

    registration.enabled = false: CHECK_MATERIALS -> ASSEMBLING, Hole geometry
      from the Mother OBB and nominal ratios every frame (original MVP flow).
    registration.enabled = true: CHECK_MATERIALS -> REGISTER_MOTHER -> ASSEMBLING.
      The Mother is locked once with measured holes; assembly uses the lock even
      when the Mother is hidden and briefly remembers hidden Hole contents.
    Pass the BGR ``image`` to update() so the holes are measured; without it
    (JSONL replay, tests) the nominal hole ratios are used for the lock.
    """

    def __init__(self, config, recipe):
        self.config = config
        self.reset(recipe)

    def reset(self, recipe=None):
        if recipe is not None:
            self.recipe = recipe
        self.machine = StateMachine(self.config)
        self.registrar = MotherRegistrar(self.config)
        self.tracker = None
        self.memory = HoleMemory(registration_config(self.config).get("occlusion_hold_ms", 1500))
        self.registration = {}
        self.ambiguous_since = None
        self.last_id = -1
        self.last_timestamp = -1
        self.event_sequence = 0

    def reregister(self):
        """Worker request (Mother replaced/pushed away): register again, keep the material result."""
        self.registrar.reset()
        self.tracker = None
        self.memory.reset()
        self.registration = {}
        if self.machine.phase == Phase.ASSEMBLING and registration_enabled(self.config):
            self.machine.phase = Phase.REGISTER_MOTHER
            self.machine.status, self.machine.confirmed = Status.HOLD, None

    def _frame_reasons(self, frame):
        reasons = []
        if frame.frame_id <= self.last_id or frame.timestamp_ms <= self.last_timestamp:
            reasons.append(Issue("OUT_OF_ORDER_FRAME"))
        else:
            if self.last_timestamp >= 0 and frame.timestamp_ms-self.last_timestamp > self.config["max_frame_gap_ms"]:
                reasons.append(Issue("FRAME_GAP"))
            self.last_id, self.last_timestamp = frame.frame_id, frame.timestamp_ms
        if not frame.input_valid:
            reasons.append(Issue("INPUT_UNAVAILABLE"))
        return reasons

    @staticmethod
    def _lock_info(lock, geometry):
        return {"locked": True, "locked_at_ms": lock.locked_at_ms,
                "hole_local": [tuple(round(v, 4) for v in h) for h in lock.hole_local],
                "holes": {k: tuple(round(v, 1) for v in p) for k, p in geometry["holes"].items()}}

    def _register(self, frame, detections, reasons, image):
        mothers = [d for d in detections if d.class_name == "mother_part"]
        components = [d for d in detections if d.class_name != "mother_part"]
        # FRAME_GAP is judged by the registrar's own, slower gap limit.
        blocking = [r for r in reasons if r.code != "FRAME_GAP"]
        if blocking:
            self.registrar._restart()
            return Candidate(Status.HOLD, tuple(sorted(blocking))), {}
        if image is not None:
            from src.vision.hole_detector import measure_holes   # OpenCV only when images are used
            measurements = {m.detection_id: measure_holes(image, m, self.config) for m in mothers}
        else:
            measurements = {m.detection_id: nominal_measurement(self.config) for m in mothers}
        status = self.registrar.update(frame.timestamp_ms, mothers, components, measurements)
        self.registration = {"progress": round(status.progress, 3), "measured": image is not None,
                             "issues": [asdict(i) for i in status.issues]}
        if image is not None and status.mother_id in measurements:
            self.registration["holes_seen"] = [
                {"hole_id": h.hole_id, "xy": (round(h.x, 1), round(h.y, 1)),
                 "visible": h.visible, "contrast": h.contrast}
                for h in measurements[status.mother_id].holes]
        if not status.locked:
            return Candidate(Status.HOLD, status.issues), {}
        self.tracker = MotherTracker(status.lock, self.config)
        self.memory.reset()
        geometry = status.lock.geometry(self.config)
        self.registration.update(self._lock_info(status.lock, geometry))
        self.machine.begin_assembly()
        return Candidate(Status.HOLD), geometry

    def _recipe_correct(self, hole, slot, detections):
        target = next((getattr(p, slot) for p in self.recipe.placements if p.mother_hole == hole), "")
        return len(detections) == 1 and detections[0]["class_name"] == target and detections[0]["orientation_ok"]

    def _assemble_registered(self, frame, detections, reasons):
        mothers = [d for d in detections if d.class_name == "mother_part"]
        lock, issues, lock_events = self.tracker.update(frame.timestamp_ms, mothers)
        geometry = lock.geometry(self.config)
        if lock_events:
            self.memory.reset()
            self.registration.update(self._lock_info(lock, geometry))
        reasons = reasons + list(issues)
        if reasons:
            self.ambiguous_since = None
            return Candidate(Status.HOLD, tuple(sorted(reasons))), geometry, {}, (), lock_events
        raw, ambiguous, ignored = associate(detections, geometry, self.config)
        geometry["ignored_detections"] = ignored
        geometry["ambiguous_detections"] = ambiguous
        observed, occluded = self.memory.apply(raw, frame.timestamp_ms, self._recipe_correct)
        candidate = evaluate(self.recipe, observed)
        # A component lying on the Mother that fits no Hole (being placed, or
        # misaligned) must not freeze the whole judgement: the other Holes are
        # still judged. It only blocks PASS, and is reported once it persists.
        if not ambiguous:
            self.ambiguous_since = None
            return candidate, geometry, observed, occluded, lock_events
        if self.ambiguous_since is None:
            self.ambiguous_since = frame.timestamp_ms
        status = Status.IN_PROGRESS if candidate.status == Status.PASS else candidate.status
        issues = candidate.issues
        hold_ms = registration_config(self.config).get("ambiguous_report_ms", 1000)
        if frame.timestamp_ms-self.ambiguous_since >= hold_ms:
            names = {d.detection_id: d.class_name for d in detections}
            issues = tuple(sorted(issues + (Issue("AMBIGUOUS_ASSOCIATION",
                                                  observed=",".join(sorted(names[i] for i in ambiguous))),)))
        return Candidate(status, issues), geometry, observed, occluded, lock_events

    def _assemble_legacy(self, detections, reasons):
        geometry, observed = {}, {}
        mothers = [d for d in detections if d.class_name == "mother_part"]
        if len(mothers) != 1:
            reasons.append(Issue("MOTHER_NOT_FOUND" if not mothers else "MULTIPLE_MOTHERS"))
        if not reasons:
            try:
                geometry = build_geometry(mother_pose(mothers[0], self.config), self.config)
            except ValueError as error:
                reasons.append(Issue(str(error)))
        if not reasons:
            observed, ambiguous, ignored = associate(detections, geometry, self.config)
            geometry["ignored_detections"] = ignored
            if ambiguous:
                reasons.append(Issue("AMBIGUOUS_ASSOCIATION", observed=",".join(ambiguous)))
        if reasons:
            return Candidate(Status.HOLD, tuple(sorted(reasons))), geometry, observed
        return evaluate(self.recipe, observed), geometry, observed

    def update(self, frame, image=None):
        geometry, observed, materials, occluded, lock_events = {}, {}, {}, (), ()
        evaluated_phase = self.machine.phase
        reasons = self._frame_reasons(frame)
        detections = tuple(d for d in frame.detections if d.confidence >= self.config["confidence_threshold"])
        if evaluated_phase == Phase.CHECK_MATERIALS:
            candidate, materials = evaluate_materials(self.recipe, detections)
            if reasons:
                candidate = Candidate(Status.HOLD, tuple(sorted(reasons)))
            stable, changed = self.machine.update(candidate, frame.timestamp_ms)
        elif evaluated_phase == Phase.REGISTER_MOTHER:
            previous = (self.machine.phase, self.machine.status)
            candidate, geometry = self._register(frame, detections, reasons, image)
            stable = self.machine.phase == Phase.ASSEMBLING
            changed = previous != (self.machine.phase, self.machine.status)
        elif self.tracker is not None:
            candidate, geometry, observed, occluded, lock_events = \
                self._assemble_registered(frame, detections, reasons)
            stable, changed = self.machine.update(candidate, frame.timestamp_ms)
        else:
            candidate, geometry, observed = self._assemble_legacy(detections, reasons)
            stable, changed = self.machine.update(candidate, frame.timestamp_ms)

        events = []
        for event in lock_events:
            self.event_sequence += 1
            events.append({"event_id": self.event_sequence, "recipe_id": self.recipe.recipe_id,
                           "phase": self.machine.phase.value, "registration": dict(self.registration),
                           **event})
        if changed:
            self.event_sequence += 1
            events.append({"event_id": self.event_sequence, "timestamp_ms": frame.timestamp_ms,
                           "recipe_id": self.recipe.recipe_id, "status": self.machine.status.value,
                           "event_type": EVENT_TYPES.get((evaluated_phase, self.machine.phase), "STATUS_CHANGED"),
                           "from_phase": evaluated_phase.value, "phase": self.machine.phase.value,
                           "materials": materials,
                           "candidate": asdict(candidate), "observed": observed,
                           "mother_pose": geometry.get("pose"),
                           "registration": dict(self.registration),
                           "calibration_status": self.config["calibration_status"]})
        return Snapshot(frame.frame_id, frame.timestamp_ms, self.recipe.recipe_id,
                        self.machine.status, candidate, self.machine.confirmed, stable,
                        self.config["calibration_status"], geometry, observed, tuple(events),
                        self.machine.phase, evaluated_phase, materials,
                        dict(self.registration), occluded)
