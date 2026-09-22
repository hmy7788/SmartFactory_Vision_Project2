"""Whole-frame inventory check, independent of placement and Mother pose."""
from collections import Counter
from src.contracts.detections import CLASSES
from src.contracts.inspection import Candidate, Issue, Status


def evaluate_materials(recipe, detections):
    expected = Counter({"mother_part": 1})
    for placement in recipe.placements:
        expected.update((placement.bolt, placement.part))
    observed = Counter(d.class_name for d in detections)
    issues = []
    for name in sorted(CLASSES):
        required, actual = expected[name], observed[name]
        if actual < required:
            issues.append(Issue("MATERIAL_MISSING", expected=f"{name}:{required}", observed=f"{name}:{actual}"))
        elif actual > required:
            code = "MATERIAL_UNEXPECTED" if required == 0 else "MATERIAL_EXCESS"
            issues.append(Issue(code, expected=f"{name}:{required}", observed=f"{name}:{actual}"))
    status = Status.READY
    if issues:
        status = Status.NG if any(i.code != "MATERIAL_MISSING" for i in issues) else Status.IN_PROGRESS
    counts = {"expected": {k: expected[k] for k in sorted(CLASSES)},
              "observed": {k: observed[k] for k in sorted(CLASSES)}}
    return Candidate(status, tuple(sorted(issues))), counts
