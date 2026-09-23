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
