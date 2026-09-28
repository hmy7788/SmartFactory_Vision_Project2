from dataclasses import asdict
from math import hypot
from src.contracts.inspection import Candidate, Issue, Snapshot, Status, Phase
from src.geometry.mother_frame import mother_pose
from src.geometry.roi_builder import build_geometry
from src.geometry.association import associate
from src.geometry.hole_assignment import HoleAssigner
from src.geometry.mother_registration import (MotherRegistrar, MotherTracker, nominal_measurement,
                                              registration_config, registration_enabled)
from src.process.evaluator import evaluate
from src.process.materials import evaluate_materials
from src.process.occlusion import HoleEvidence
from src.process.state_machine import StateMachine

EVENT_TYPES = {
    (Phase.CHECK_MATERIALS, Phase.ASSEMBLING): "ASSEMBLY_STARTED",      # registration disabled
    (Phase.CHECK_MATERIALS, Phase.REGISTER_MOTHER): "MATERIALS_READY",
    (Phase.REGISTER_MOTHER, Phase.ASSEMBLING): "ASSEMBLY_STARTED",
    (Phase.ASSEMBLING, Phase.RESULT): "PRODUCT_RESULT",
    (Phase.RESULT, Phase.ASSEMBLING): "REASSEMBLY_STARTED",
}

ASSEMBLY_DEFAULTS = {
    "pass_confirm_ms": 2000,      # PASS kept this long -> final PASS (automatic)
    "ng_alert_ms": 400,           # confirmed NG kept this long -> red alert (after stable_duration)
    "occluded_weight": 0.3,       # vote weight of frames where the Mother is (partly) hidden
    "evidence_keep_ms": 1400,     # decay time of recipe-correct contents (hidden bolt kept ~1.5 s)
    "evidence_drop_ms": 80,       # decay time of wrong contents (NG clears right after removal)
    "evidence_threshold": 0.35,
}


def assembly_config(config):
    merged = dict(ASSEMBLY_DEFAULTS)
    merged.update(config.get("assembly", {}))
    return merged


class InspectionService:
    """Frame loop core.

    registration.enabled = false: CHECK_MATERIALS -> ASSEMBLING, Hole geometry
      from the Mother OBB and nominal ratios every frame (original MVP flow).
    registration.enabled = true:
      CHECK_MATERIALS -> REGISTER_MOTHER -> ASSEMBLING -> RESULT
      * The Mother is locked once with measured holes. The lock follows small
        drift (Mother detection, seated bolts) and re-locks after a large move.
      * Components go to the nearest hole (lenient, boundary zone between holes,
        sticky), and per-hole time-decayed votes keep hidden contents.
      * RESULT: PASS kept ``pass_confirm_ms`` -> final PASS automatically, or the
        worker calls complete() -> final PASS/NG. reassemble() goes back after
        an NG, reset(recipe) starts the next product.
    Pass the BGR ``image`` to update() so the holes are measured; without it
    (JSONL replay, tests) the nominal hole ratios are used for the lock.
    """

    def __init__(self, config, recipe):
        self.config = config
        self.product_seq = 0
        self.reset(recipe)

    def reset(self, recipe=None):
        """New product (optionally a new recipe): back to CHECK_MATERIALS."""
        if recipe is not None:
            self.recipe = recipe
        self.acfg = assembly_config(self.config)
        self.machine = StateMachine(self.config)
        self.registrar = MotherRegistrar(self.config)
        self.tracker = None
        self.assigner = HoleAssigner(self.config)
        self.evidence = self._new_evidence()
        self.registration = {}
        self.ambiguous_since = None
        self.pass_since = None
        self.ng_since = None
        self.alert = ""
        self.result = {}
        self.assembly_started_ms = None
        self.issue_history = set()
        self.pending_events = []
        self.last_id = -1
        self.last_timestamp = -1
        self.event_sequence = 0

    def _new_evidence(self):
        return HoleEvidence(self.acfg["evidence_keep_ms"], self.acfg["evidence_drop_ms"],
                            self.acfg["evidence_threshold"])

    # ---- worker actions -------------------------------------------------
    def reregister(self):
        """Mother replaced/pushed away: register again, keep the material result."""
        self.registrar.reset()
        self.tracker = None
        self.assigner.reset()
        self.evidence.reset()
        self.registration = {}
        self._clear_assembly_state()
        if self.machine.phase in (Phase.ASSEMBLING, Phase.RESULT) and registration_enabled(self.config):
            self.machine.phase = Phase.REGISTER_MOTHER
            self.machine.status, self.machine.confirmed = Status.HOLD, None

    def complete(self):
        """Worker says 'assembly finished' -> final verdict now (PASS only if confirmed PASS)."""
        if self.machine.phase != Phase.ASSEMBLING:
            return False
        confirmed = self.machine.confirmed
        if self.machine.status == Status.PASS and confirmed is not None:
            self._finish(Status.PASS, confirmed, self.last_timestamp, "manual")
        else:
            candidate = confirmed or Candidate(Status.NG)
            self._finish(Status.NG, Candidate(Status.NG, candidate.issues), self.last_timestamp, "manual")
        return True

    def reassemble(self):
        """After a final NG: go back to ASSEMBLING with the same Mother lock."""
        if self.machine.phase != Phase.RESULT:
            return False
        self.machine.resume_assembly()
        self.evidence.reset()
        self.assigner.reset()
        self._clear_assembly_state()
        self.pending_events.append({"event_type": "REASSEMBLY_STARTED", "timestamp_ms": self.last_timestamp})
        return True

    def _clear_assembly_state(self):
        self.pass_since, self.ng_since, self.alert = None, None, ""
        self.result, self.ambiguous_since = {}, None

    def _finish(self, status, candidate, timestamp_ms, decided_by):
        self.product_seq += 1
        self.result = {"product_seq": self.product_seq, "recipe_id": self.recipe.recipe_id,
                       "result": status.value, "decided_by": decided_by,
                       "issues": [asdict(i) for i in candidate.issues],
                       "issue_history": sorted(self.issue_history),
                       "assembly_ms": None if self.assembly_started_ms is None
                       else round(timestamp_ms-self.assembly_started_ms)}
        self.machine.finish(status, candidate)
        self.alert = ""
        self.pending_events.append({"event_type": "PRODUCT_RESULT", "timestamp_ms": timestamp_ms,
                                    "status": status.value, "result": dict(self.result)})

    # ---- frame helpers --------------------------------------------------
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
        self.assigner.reset()
        self.evidence.reset()
        geometry = status.lock.geometry(self.config)
        self.registration.update(self._lock_info(status.lock, geometry))
        self.machine.begin_assembly()
        self.assembly_started_ms = frame.timestamp_ms
        return Candidate(Status.HOLD), geometry

    def _recipe_correct(self, hole, slot, detections):
        target = next((getattr(p, slot) for p in self.recipe.placements if p.mother_hole == hole), "")
        return len(detections) == 1 and detections[0]["class_name"] == target and detections[0]["orientation_ok"]

    def _assemble_registered(self, frame, detections, reasons):
        mothers = [d for d in detections if d.class_name == "mother_part"]
        lock, issues, lock_events = self.tracker.update(frame.timestamp_ms, mothers)
        geometry = lock.geometry(self.config)
        if lock_events:
            self.evidence.reset()
            self.assigner.reset()
        self.registration.update(self._lock_info(lock, geometry))
        reasons = reasons + list(issues)
        if reasons:
            self.ambiguous_since = None
            return Candidate(Status.HOLD, tuple(sorted(reasons))), geometry, {}, (), lock_events
        raw, ambiguous, ignored = self.assigner.assign(detections, geometry)
        geometry["ignored_detections"] = ignored
        geometry["ambiguous_detections"] = ambiguous
        # Seated bolts are landmarks: pull the hole grid onto them (small drift).
        holes = geometry["holes"]
        step = hypot(holes[5][0]-holes[1][0], holes[5][1]-holes[1][1])/4 if 1 in holes and 5 in holes else 0
        limit = registration_config(self.config)["landmark_max_distance_ratio"]
        landmarks = [(holes[h], d["point"]) for h, slots in raw.items() for d in slots["bolt"]
                     if len(slots["bolt"]) == 1 and d["offset_steps"] <= limit]
        self.tracker.refine(landmarks, step)
        # Frames where the Mother is not fully visible (hand over it) count less.
        visible = any(self.tracker._reliable(m) for m in mothers)
        weight = 1.0 if visible else self.acfg["occluded_weight"]
        observed, occluded = self.evidence.apply(raw, frame.timestamp_ms, self._recipe_correct, weight)
        candidate = evaluate(self.recipe, observed)
        # A component on the Mother that fits no Hole (being placed, boundary
        # zone) never freezes the judgement: other holes are still judged, it
        # only blocks PASS and is reported once it persists.
        if not ambiguous:
            self.ambiguous_since = None
            return candidate, geometry, observed, occluded, lock_events
        if self.ambiguous_since is None:
            self.ambiguous_since = frame.timestamp_ms
        status = Status.IN_PROGRESS if candidate.status == Status.PASS else candidate.status
        issues = candidate.issues
        if frame.timestamp_ms-self.ambiguous_since >= registration_config(self.config).get("ambiguous_report_ms", 1000):
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

    def _verdict_and_alert(self, timestamp_ms, events):
        """Registered flow only: red alert on lasting confirmed NG, automatic final PASS."""
        status = self.machine.status
        for issue in (self.machine.confirmed.issues if self.machine.confirmed else ()):
            if status == Status.NG:
                self.issue_history.add(f"{issue.code}:H{issue.hole_id}")
        if status == Status.NG:
            self.ng_since = timestamp_ms if self.ng_since is None else self.ng_since
            if not self.alert and timestamp_ms-self.ng_since >= self.acfg["ng_alert_ms"]:
                self.alert = "NG"
                events.append({"event_type": "NG_ALERT", "timestamp_ms": timestamp_ms,
                               "issues": [asdict(i) for i in self.machine.confirmed.issues]})
        else:
            if self.alert:
                events.append({"event_type": "NG_CLEARED", "timestamp_ms": timestamp_ms})
            self.ng_since, self.alert = None, ""
        if status == Status.PASS:
            self.pass_since = timestamp_ms if self.pass_since is None else self.pass_since
            if timestamp_ms-self.pass_since >= self.acfg["pass_confirm_ms"]:
                self._finish(Status.PASS, self.machine.confirmed, timestamp_ms, "auto")
        else:
            self.pass_since = None

    # ---- main entry -----------------------------------------------------
    def update(self, frame, image=None):
        geometry, observed, materials, occluded, lock_events = {}, {}, {}, (), ()
        evaluated_phase = self.machine.phase
        reasons = self._frame_reasons(frame)
        detections = tuple(d for d in frame.detections if d.confidence >= self.config["confidence_threshold"])
        extra = list(self.pending_events)
        self.pending_events = []
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
        elif evaluated_phase == Phase.RESULT:
            # Final verdict is frozen until reset(next recipe) / reassemble().
            candidate, stable, changed = self.machine.confirmed or Candidate(self.machine.status), True, False
            if self.tracker is not None:
                geometry = self.tracker.lock.geometry(self.config)
        elif self.tracker is not None:
            candidate, geometry, observed, occluded, lock_events = \
                self._assemble_registered(frame, detections, reasons)
            previous = (self.machine.phase, self.machine.status, self.machine.confirmed)
            stable, _ = self.machine.update(candidate, frame.timestamp_ms)
            self._verdict_and_alert(frame.timestamp_ms, extra)
            extra += self.pending_events
            self.pending_events = []
            changed = previous != (self.machine.phase, self.machine.status, self.machine.confirmed)
        else:
            candidate, geometry, observed = self._assemble_legacy(detections, reasons)
            stable, changed = self.machine.update(candidate, frame.timestamp_ms)

        events = []
        for event in list(lock_events) + extra:
            self.event_sequence += 1
            events.append({"event_id": self.event_sequence, "recipe_id": self.recipe.recipe_id,
                           "phase": self.machine.phase.value, "registration": dict(self.registration),
                           **event})
        if changed and not any(e["event_type"] == "PRODUCT_RESULT" for e in extra):
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
                        dict(self.registration), occluded, self.alert, dict(self.result))
