"""Non-blocking alert sounds (Windows winsound; terminal bell elsewhere).

Put your own WAV files in assets/sounds/<kind>.wav to replace the beeps:
  step (stage done), ok (registration done), ng (wrong assembly),
  pass (final PASS), fail (final NG)
"""
import sys
import threading
import time
from pathlib import Path

BEEPS = {                      # (frequency Hz, duration ms) sequences
    "step": [(880, 120), (1320, 160)],
    "ok": [(988, 120), (1318, 220)],
    "ng": [(440, 250), (0, 80), (440, 250)],
    "pass": [(784, 120), (988, 120), (1318, 300)],
    "fail": [(392, 300), (262, 500)],
}


class Sounder:
    def __init__(self, enabled=True, sounds_dir=None, cooldown_ms=None):
        self.enabled = enabled
        self.dir = Path(sounds_dir) if sounds_dir else None
        self.cooldown_ms = cooldown_ms or {"ng": 2000}
        self.last = {}
        try:
            import winsound
            self.winsound = winsound
        except ImportError:
            self.winsound = None

    def play(self, kind):
        if not self.enabled:
            return
        now = time.monotonic()*1000
        if now-self.last.get(kind, -1e9) < self.cooldown_ms.get(kind, 300):
            return
        self.last[kind] = now
        wav = self.dir/f"{kind}.wav" if self.dir else None
        if self.winsound and wav is not None and wav.exists():
            self.winsound.PlaySound(str(wav), self.winsound.SND_FILENAME | self.winsound.SND_ASYNC)
            return
        threading.Thread(target=self._beep, args=(kind,), daemon=True).start()

    def _beep(self, kind):
        for freq, ms in BEEPS.get(kind, [(1000, 150)]):
            if self.winsound is None:
                sys.stdout.write("\a")
                sys.stdout.flush()
                time.sleep(ms/1000)
            elif freq == 0:
                time.sleep(ms/1000)
            else:
                self.winsound.Beep(freq, ms)
