"""Per-Hole memory so a hand or part hiding a component is not "missing".

"Not seen" is not "absent": when a Hole slot that had a component suddenly
shows nothing, its last observation is kept for ``occlusion_hold_ms``. A new or
different component replaces the memory immediately (the state machine's own
stable_duration still confirms it). Removal therefore takes hold_ms longer to
be reported, which is intended: taking a correct bolt out again is rare,
occlusion is constant.

Only contents accepted by ``keep(hole, slot, detections)`` are remembered. The
service keeps just recipe-correct contents, so when the worker removes a wrong
bolt the NG clears at once instead of lingering for hold_ms.
"""

DEFAULT_HOLD_MS = 1500


class HoleMemory:
    def __init__(self, hold_ms=DEFAULT_HOLD_MS):
        self.hold_ms = hold_ms
        self.memory = {}          # (hole, slot) -> (detections, last_seen_ms)

    def reset(self):
        self.memory = {}

    def apply(self, observed, timestamp_ms, keep=None):
        """observed: {hole: {"bolt": [...], "part": [...]}} -> (observed', occluded holes)."""
        result, occluded = {}, set()
        for hole, slots in observed.items():
            result[hole] = {}
            for slot, detections in slots.items():
                key = (hole, slot)
                if detections:
                    if keep is None or keep(hole, slot, detections):
                        self.memory[key] = (detections, timestamp_ms)
                    else:
                        self.memory.pop(key, None)
                    result[hole][slot] = detections
                    continue
                remembered = self.memory.get(key)
                if remembered and timestamp_ms-remembered[1] <= self.hold_ms:
                    result[hole][slot] = [dict(d, held=True) for d in remembered[0]]
                    occluded.add(hole)
                else:
                    self.memory.pop(key, None)
                    result[hole][slot] = []
        return result, tuple(sorted(occluded))


class HoleEvidence:
    """Per-Hole time-decayed voting (replaces HoleMemory in the registered flow).

    Every frame each Hole slot gets a vote ``confidence x visibility`` for the
    class seen there. ``visibility`` is lowered by the service when the frame is
    probably occluded (hand over the Mother), so frames from before the hand
    outweigh frames taken while the hand is there.

    * Scores decay with time. Recipe-correct contents decay slowly
      (``keep_ms``), wrong contents fast (``drop_ms``): a hidden correct bolt is
      kept ~1.5 s, a removed wrong bolt disappears at once so the NG clears.
    * Seeing a different class in the slot weakens the others (conflict),
      scaled by visibility.
    * A slot shows the top class whose score >= ``threshold``.
    * Two or more components in one slot are passed through unchanged
      (EXTRA_COMPONENT must stay visible).
    """

    def __init__(self, keep_ms=1400, drop_ms=80, threshold=0.35, conflict=0.5):
        self.keep_ms, self.drop_ms = keep_ms, drop_ms
        self.threshold, self.conflict = threshold, conflict
        self.reset()

    def reset(self):
        self.slots = {}            # (hole, slot) -> {"scores": {cls: s}, "last": {cls: det}, "t": ms}

    def apply(self, observed, timestamp_ms, keep=None, visibility=1.0):
        from math import exp
        result, occluded = {}, set()
        for hole, slots in observed.items():
            result[hole] = {}
            for slot, detections in slots.items():
                key = (hole, slot)
                state = self.slots.setdefault(key, {"scores": {}, "last": {}, "t": timestamp_ms})
                dt = max(0.0, timestamp_ms-state["t"])
                state["t"] = timestamp_ms
                for cls in list(state["scores"]):
                    correct = keep is None or keep(hole, slot, [state["last"][cls]])
                    tau = self.keep_ms if correct else self.drop_ms
                    tau *= 1.0 if visibility >= 1.0 else 2.0            # decay slower while occluded
                    state["scores"][cls] *= exp(-dt/tau)
                if len(detections) > 1:
                    state["scores"], state["last"] = {}, {}
                    result[hole][slot] = detections
                    continue
                if detections:
                    d = detections[0]
                    cls = d["class_name"]
                    w = min(1.0, d.get("confidence", 1.0))*visibility
                    for other in state["scores"]:
                        if other != cls:
                            state["scores"][other] *= 1-self.conflict*visibility
                    s = state["scores"].get(cls, 0.0)
                    state["scores"][cls] = s + w*(1-s)
                    state["last"][cls] = d
                for cls in [c for c, s in state["scores"].items() if s < 0.02]:
                    state["scores"].pop(cls)
                    state["last"].pop(cls, None)
                best = max(state["scores"].items(), key=lambda kv: kv[1], default=(None, 0.0))
                if best[0] is None or best[1] < self.threshold:
                    result[hole][slot] = []
                elif detections and detections[0]["class_name"] == best[0]:
                    result[hole][slot] = detections
                else:
                    result[hole][slot] = [dict(state["last"][best[0]], held=True)]
                    occluded.add(hole)
        return result, tuple(sorted(occluded))
