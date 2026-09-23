from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    NG = "NG"
    HOLD = "HOLD"


class Phase(str, Enum):
    CHECK_MATERIALS = "CHECK_MATERIALS"
    REGISTER_MOTHER = "REGISTER_MOTHER"   # only when config registration.enabled
    ASSEMBLING = "ASSEMBLING"


@dataclass(frozen=True, order=True)
class Issue:
    code: str
    hole_id: int = 0
    expected: str = ""
    observed: str = ""


@dataclass(frozen=True)
class Candidate:
    status: Status
    issues: tuple[Issue, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    frame_id: int
    timestamp_ms: float
    recipe_id: str
    status: Status
    candidate: Candidate
    confirmed: Candidate | None
    stable: bool
    calibration_status: str
    geometry: dict
    observed: dict
    events: tuple[dict, ...]
    phase: Phase
    evaluated_phase: Phase
    materials: dict
    # Mother registration: progress 0..1, locked hole points, measured flag.
    registration: dict = field(default_factory=dict)
    # Holes whose content is currently remembered because it is hidden (hand, part).
    occluded: tuple[int, ...] = ()
