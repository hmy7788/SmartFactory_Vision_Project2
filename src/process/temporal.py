from src.contracts.inspection import Status


class TemporalFilter:
    def __init__(self, duration_ms, max_gap_ms):
        self.duration_ms = duration_ms
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self):
        self.key = None
        self.since = None
        self.previous = None
        self.count = 0

    def update(self, candidate, timestamp_ms):
        if candidate.status == Status.HOLD:
            self.reset()
            return False
        gap = self.previous is not None and timestamp_ms-self.previous > self.max_gap_ms
        if candidate != self.key or gap:
            self.key, self.since, self.count = candidate, timestamp_ms, 0
        self.previous = timestamp_ms
        self.count += 1
        return self.count >= 2 and timestamp_ms-self.since >= self.duration_ms
