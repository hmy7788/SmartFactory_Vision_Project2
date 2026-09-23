import json
from math import isfinite
from pathlib import Path


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    positive = ("bolt_half_width_ratio", "bolt_half_height_ratio", "part_anchor_tolerance_ratio",
                "stable_duration_ms", "material_stable_duration_ms", "max_frame_gap_ms")
    for name in positive:
        if not isfinite(config[name]) or config[name] <= 0:
            raise ValueError(f"{name} must be finite and positive")
    for name in ("confidence_threshold", "part_overlap_threshold"):
        if not 0 < config[name] <= 1:
            raise ValueError(f"{name} must be in (0, 1]")
    for name in ("max_mother_angle_deg", "part_max_angle_deg"):
        if not 0 < config[name] < 90:
            raise ValueError(f"{name} must be in (0, 90)")
    alphas = config["hole_alphas"]
    if len(alphas) != 5 or not all(isfinite(x) and -0.5 < x < 0.5 for x in alphas):
        raise ValueError("Exactly five normalized Hole positions required")
    if any(a >= b for a, b in zip(alphas, alphas[1:])):
        raise ValueError("Hole positions must increase left to right")
    if not isfinite(config["hole_beta"]) or abs(config["hole_beta"]) > 0.5:
        raise ValueError("Invalid hole_beta")
    if set(config["part_rois"]) != {"part_2hole", "part_3hole"}:
        raise ValueError("Both Part ROI definitions are required")
    for roi in config["part_rois"].values():
        for name in ("width_ratio", "length_ratio", "offset_ratio"):
            if not isfinite(roi[name]) or roi[name] <= 0:
                raise ValueError(f"Invalid Part ROI {name}")
    if not isinstance(config.get("calibration_status"), str):
        raise ValueError("calibration_status is required")
    return config
