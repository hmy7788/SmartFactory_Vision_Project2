from src.contracts.inspection import Status, Phase
from .temporal import TemporalFilter


class StateMachine:
    """One-way material gate followed by continuous assembly inspection."""

    def __init__(self, config):
        self.config = config
        self.phase = Phase.CHECK_MATERIALS
        self.filter = TemporalFilter(config["material_stable_duration_ms"], config["max_frame_gap_ms"])
        self.confirmed = None
        self.status = Status.HOLD

    def update(self, candidate, timestamp_ms):
        stable = self.filter.update(candidate, timestamp_ms)
        previous = (self.phase, self.status, self.confirmed)
        if candidate.status == Status.HOLD:
            self.status, self.confirmed = Status.HOLD, None
        elif stable:
            self.status, self.confirmed = candidate.status, candidate
            if self.phase == Phase.CHECK_MATERIALS and candidate.status == Status.READY:
                registration = self.config.get("registration", {}).get("enabled", False)
                self.phase = Phase.REGISTER_MOTHER if registration else Phase.ASSEMBLING
                # No readiness evidence is carried into assembly PASS evidence.
                self.filter = TemporalFilter(self.config["stable_duration_ms"], self.config["max_frame_gap_ms"])
                self.status, self.confirmed = Status.HOLD, None
        # During a short transient retain the last confirmed result, but expose
        # stable=False and the fresh candidate; HOLD is immediate invalidation.
        changed = previous != (self.phase, self.status, self.confirmed)
        return stable, changed

    def begin_assembly(self):
        """REGISTER_MOTHER -> ASSEMBLING once the Mother lock exists."""
        self.phase = Phase.ASSEMBLING
        self.filter = TemporalFilter(self.config["stable_duration_ms"], self.config["max_frame_gap_ms"])
        self.status, self.confirmed = Status.HOLD, None
