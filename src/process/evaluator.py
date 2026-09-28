from src.contracts.inspection import Candidate, Issue, Status

_STATUS_ORDER = {Status.PASS: 0, Status.IN_PROGRESS: 1, Status.NG: 2}


def evaluate_symmetric(recipe, observed, config):
    """
    The Mother bar is symmetric, so one physical assembly read from its other end numbers the
    Holes H1<->H5, H2<->H4. Try both readings and keep the one that fits the recipe better.
    A genuine 180-degree rotation of the whole rigid assembly flips the Hole numbering AND
    moves every part to Mother's opposite side at the same time (not just one lone part) --
    so the mirrored reading requires "below" specifically, regardless of allow_parts_below
    (which only relaxes the *direct*, non-rotated reading).
    Returns (candidate, mirrored); issue hole ids follow the winning (recipe) numbering.
    """
    direct_side = None if config.get("allow_parts_below") else "above"
    direct = evaluate(recipe, observed, direct_side)
    mirrored = evaluate(recipe, {6 - hole: slots for hole, slots in observed.items()}, "below")
    rank = lambda c: (_STATUS_ORDER[c.status], len(c.issues))
    return (mirrored, True) if rank(mirrored) < rank(direct) else (direct, False)


def evaluate(recipe, observed, expected_side=None):
    """expected_side: when given ("above"/"below"), a part's "side" (from association.py) that
    doesn't match it raises PART_WRONG_SIDE. None skips the side check entirely."""
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
                if slot == "part" and expected_side is not None and d["side"] != expected_side:
                    errors.append(Issue("PART_WRONG_SIDE", hole, target, d["class_name"]))
    # No final-missing NG without an end-of-work signal.
    status = Status.NG if errors else Status.IN_PROGRESS if missing else Status.PASS
    return Candidate(status, tuple(sorted(errors+missing)))
