from src.contracts.inspection import Candidate, Issue, Status


def evaluate(recipe, observed):
    expected = {p.mother_hole: p for p in recipe.placements}
    errors, missing = [], []
    for hole, slots in observed.items():
        requirement = expected.get(hole)
        for slot, detections in slots.items():
            target = getattr(requirement, slot) if requirement else ""
            if not target:
                errors.extend(Issue("UNEXPECTED_COMPONENT", hole, "", d["class_name"]) for d in detections)
                continue
            if not detections:
                missing.append(Issue("MISSING_"+slot.upper(), hole, target))
            if len(detections) > 1:
                errors.append(Issue("EXTRA_COMPONENT", hole, target, ",".join(sorted(d["class_name"] for d in detections))))
            for d in detections:
                if d["class_name"] != target:
                    errors.append(Issue("WRONG_"+slot.upper(), hole, target, d["class_name"]))
                if not d["orientation_ok"]:
                    errors.append(Issue("PART_ORIENTATION_ERROR", hole, target, d["class_name"]))
    # No final-missing NG without an end-of-work signal.
    status = Status.NG if errors else Status.IN_PROGRESS if missing else Status.PASS
    return Candidate(status, tuple(sorted(errors+missing)))
