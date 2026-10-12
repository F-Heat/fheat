"""Cooperative cancellation of a running calculation.

The caller hands over a ``should_stop`` function — to
:class:`fheat_core.orchestrator.FHeatOrchestrator` or :func:`cancellable`.
The pipeline asks it at checkpoints between its parts and, in the expert
mode, while HiGHS optimises; once it returns True the calculation ends with
:class:`CalculationCancelled`. Without a ``should_stop`` nothing changes.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

ShouldStop = Callable[[], bool]

_should_stop: ContextVar[Optional[ShouldStop]] = ContextVar("fheat_should_stop", default=None)

#: s, longest pause between two checks in :func:`sleep`
_SLEEP_STEP = 0.5


class CalculationCancelled(BaseException):
    """The caller asked the running calculation to stop.

    A ``BaseException`` like ``KeyboardInterrupt``: the ``except Exception``
    blocks of the pipeline (a retried download, a layer that may fail) must
    not swallow it. The state of the step is undefined afterwards, as after
    any other failure.
    """


@contextmanager
def cancellable(should_stop: Optional[ShouldStop]) -> Iterator[None]:
    """Make ``should_stop`` the stop check of the code run inside the block.

    ``should_stop`` should be cheap and thread-safe: the optimisation asks it
    from the solver's thread, at most twice a second. None keeps the check
    of an enclosing block.
    """
    if should_stop is None:
        yield
        return
    token = _should_stop.set(should_stop)
    try:
        yield
    finally:
        _should_stop.reset(token)


def current_check() -> Optional[ShouldStop]:
    """The stop check in effect, for a callback that runs on another thread."""
    return _should_stop.get()


def raise_if_cancelled() -> None:
    """Checkpoint: raise :class:`CalculationCancelled` once a stop is requested."""
    should_stop = _should_stop.get()
    if should_stop is not None and should_stop():
        raise CalculationCancelled("The calculation was cancelled.")


def sleep(seconds: float) -> None:
    """``time.sleep`` that ends early with :class:`CalculationCancelled`."""
    if _should_stop.get() is None:
        time.sleep(seconds)
        return
    end = time.monotonic() + seconds
    while True:
        raise_if_cancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, _SLEEP_STEP))
