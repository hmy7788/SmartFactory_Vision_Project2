from dataclasses import dataclass
from math import isfinite

CLASSES = frozenset({"mother_part", "bolt_1", "bolt_2", "part_2hole", "part_3hole"})


@dataclass(frozen=True)
class OBBDetection:
    """Original-image pixels; radians from image +x toward +y (down)."""

    detection_id: str
    class_name: str
    confidence: float
    center_xy: tuple[float, float]
    width: float
    height: float
    angle_rad: float

    def __post_init__(self):
        if not self.detection_id or self.class_name not in CLASSES:
            raise ValueError("Invalid detection identity/class")
        values = (*self.center_xy, self.width, self.height, self.angle_rad, self.confidence)
        if len(self.center_xy) != 2 or not all(isfinite(x) for x in values):
            raise ValueError("OBB must contain finite numeric values")
        if self.width <= 0 or self.height <= 0 or not 0 <= self.confidence <= 1:
            raise ValueError("Invalid OBB dimensions/confidence")


@dataclass(frozen=True)
class DetectionFrame:
    frame_id: int
    timestamp_ms: float
    detections: tuple[OBBDetection, ...]
    input_valid: bool = True

    def __post_init__(self):
        if self.frame_id < 0 or not isfinite(self.timestamp_ms) or self.timestamp_ms < 0:
            raise ValueError("Invalid frame identity/timestamp")
        ids = [d.detection_id for d in self.detections]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate detection_id in frame")

    @classmethod
    def from_dict(cls, data):
        detections = tuple(
            OBBDetection(**{**d, "center_xy": tuple(d["center_xy"])})
            for d in data["detections"]
        )
        return cls(data["frame_id"], data["timestamp_ms"], detections, data.get("input_valid", True))
