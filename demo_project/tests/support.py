"""Helpers shared by the demo tests."""

import os
import time

SCALE_ENV = "TB_LATENCY_SCALE"


def latency_scale() -> float:
    """Multiplier applied to every simulated wait.

    The suite runs for a bit over two minutes at the default scale, which is
    the point: a 60s budget has to leave something out. That is slow for a
    local edit loop, so set TB_LATENCY_SCALE=0.02 while iterating.

    Recorded durations are only meaningful at scale 1.0. Anything measured at
    a reduced scale will make the scheduler plan against numbers that do not
    describe the real suite, so pass --no-history when running scaled down.
    """
    try:
        value = float(os.environ.get(SCALE_ENV, "1"))
    except ValueError:
        return 1.0
    return max(0.0, value)


def simulate_io(seconds: float) -> None:
    """Stand in for network or disk latency.

    The demo app is pure arithmetic and would finish in microseconds, which
    leaves a time budget nothing to schedule around. These waits give the
    suite a realistic duration spread. They are simulated, not measured work.
    """
    time.sleep(seconds * latency_scale())
