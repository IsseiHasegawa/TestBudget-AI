"""Helpers shared by the demo tests."""

import time


def simulate_io(seconds: float) -> None:
    """Stand in for network or disk latency.

    The demo app is pure arithmetic and would finish in microseconds, which
    leaves a time budget nothing to schedule around. These sleeps give the
    suite a realistic duration spread. They are simulated, not measured work.
    """
    time.sleep(seconds)
