from dataclasses import asdict
from src.contracts.inspection import Candidate, Issue, Snapshot, Status, Phase
from src.geometry.mother_frame import mother_pose
from src.geometry.roi_builder import build_geometry
from src.geometry.association import associate
from src.process.evaluator import evaluate
from src.process.materials import evaluate_materials
from src.process.state_machine import StateMachine


class InspectionService:
    def __init__(self, config, recipe):
        self.config = config
        self.reset(recipe)

    def reset(self, recipe=None):
        if recipe is not None:
            self.recipe = recipe
        self.machine = StateMachine(self.config)
        self.last_id = -1
        self.last_timestamp = -1
        self.event_sequence = 0

    def update(self, frame):
        geometry, observed = {}, {}
        materials = {}
        evaluated_phase = self.machine.phase
        reasons = []
        if frame.frame_id <= self.last_id or frame.timestamp_ms <= self.last_timestamp:
            reasons.append(Issue("OUT_OF_ORDER_FRAME"))
        else:
            if self.last_timestamp >= 0 and frame.timestamp_ms-self.last_timestamp > self.config["max_frame_gap_ms"]:
                reasons.append(Issue("FRAME_GAP"))
            self.last_id, self.last_timestamp = frame.frame_id, frame.timestamp_ms
        if not frame.input_valid:
            reasons.append(Issue("INPUT_UNAVAILABLE"))
        detections = tuple(d for d in frame.detections if d.confidence >= self.config["confidence_threshold"])
        if evaluated_phase == Phase.CHECK_MATERIALS:
            candidate, materials = evaluate_materials(self.recipe, detections)
        else:
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
            candidate = evaluate(self.recipe, observed) if not reasons else Candidate(Status.HOLD)
        if reasons:
            candidate = Candidate(Status.HOLD, tuple(sorted(reasons)))
        stable, changed = self.machine.update(candidate, frame.timestamp_ms)
        events = []
        if changed:
            self.event_sequence += 1
            events.append({"event_id": self.event_sequence, "timestamp_ms": frame.timestamp_ms,
                           "recipe_id": self.recipe.recipe_id, "status": self.machine.status.value,
                           "event_type": "ASSEMBLY_STARTED" if evaluated_phase != self.machine.phase else "STATUS_CHANGED",
                           "from_phase": evaluated_phase.value, "phase": self.machine.phase.value,
                           "materials": materials,
                           "candidate": asdict(candidate), "observed": observed,
                           "mother_pose": geometry.get("pose"),
                           "calibration_status": self.config["calibration_status"]})
        return Snapshot(frame.frame_id, frame.timestamp_ms, self.recipe.recipe_id,
                        self.machine.status, candidate, self.machine.confirmed, stable,
                        self.config["calibration_status"], geometry, observed, tuple(events),
                        self.machine.phase, evaluated_phase, materials)
