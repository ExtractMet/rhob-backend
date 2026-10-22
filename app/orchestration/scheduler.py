"""Background ticker that advances 'playing' sessions at a time-compression factor.

speed = simulated seconds per wall-clock second (e.g. 10 = 10x real time). Each tick
advances by speed x elapsed wall time, bounded to 120 s simulated per tick so the API stays
responsive. Paused sessions are never advanced (frozen clock)."""
from __future__ import annotations

import threading
import time

from .simulation_runner import MANAGER


class Ticker:
    def __init__(self, period_s: float = 1.0):
        self.period = period_s
        self._stop = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="rhob-ticker", daemon=True)
            self.thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            now = time.time()
            for s in list(MANAGER.sessions.values()):
                try:
                    if s.playing and not s.paused and s.status not in ("completed", "failed"):
                        dt = min((now - s.last_step_wall) * s.speed, 120.0)
                        if dt >= 1.0:
                            s.last_step_wall = now
                            s.step(dt_s=dt, persist=True)
                        if s.status in ("completed", "failed"):
                            s.playing = False
                except Exception as exc:  # never kill the ticker
                    s.playing = False
                    s.twin._event("TICKER_ERROR", str(exc), severity="alarm")
            self._stop.wait(self.period)


TICKER = Ticker()
