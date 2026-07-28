"""Collector protocol and the shared plumbing for building observations.

A collector's only job is to turn one reading of the machine into typed
``Observation`` values with honest provenance. Collectors do not interpret, do
not compare against thresholds, and do not decide anything -- that is the
detectors' job. Keeping the split strict is what allows the whole detection
layer to be unit-tested against recorded observations with no Windows in sight.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import JsonValue

from warden.contracts import (
    Mechanism,
    Observation,
    ObservationKind,
    ProbeError,
    ProbeResult,
    Provenance,
)

log = logging.getLogger(__name__)


class Collector(ABC):
    """Base for everything that reads the machine.

    ``probe()`` is synchronous and blocking on purpose: WMI and subprocess calls
    are blocking whatever we wrap them in, and pretending otherwise buys nothing.
    The orchestrator runs collectors on a thread pool.
    """

    id: str
    interval_s: float = 3.0
    #: Cheap collectors run every tick; expensive ones (event log, driver
    #: enumeration) declare a longer interval and are skipped in between.
    description: str = ""

    @abstractmethod
    def probe(self) -> ProbeResult:
        """Read the machine once. Must not raise; return errors in the result."""

    def warmup(self) -> None:  # noqa: B027 - an optional hook, deliberately not abstract
        """Pay any one-off cost before monitoring starts.

        Called once, on a worker thread, behind the startup splash. Collectors
        whose first reading would be meaningless -- anything measuring a rate,
        which needs two samples before it can report one -- establish their
        baseline here rather than publishing a plausible-looking zero.
        """

    def close(self) -> None:  # noqa: B027 - an optional hook, deliberately not abstract
        """Release anything held open. Called once on shutdown.

        Empty on purpose: most collectors hold nothing, and forcing every one of
        them to write an empty override would be noise. Only the two that own a
        thread pool or a .NET handle implement it.
        """

    # -- helpers for subclasses -------------------------------------------

    def observation(
        self,
        source: str,
        kind: ObservationKind,
        value: JsonValue,
        *,
        probe: str,
        mechanism: Mechanism,
        elapsed_ms: float,
        unit: str | None = None,
        confidence: float = 1.0,
        raw_ref: str | None = None,
    ) -> Observation:
        return Observation(
            source=source,
            kind=kind,
            value=value,
            unit=unit,
            confidence=confidence,
            provenance=Provenance(
                probe=probe,
                mechanism=mechanism,
                elapsed_ms=int(elapsed_ms),
                raw_ref=raw_ref,
            ),
        )

    def failure(self, probe: str, exc: BaseException | str) -> ProbeError:
        message = str(exc)
        log.debug("%s probe failed: %s", self.id, message)
        return ProbeError(source=self.id, probe=probe, message=message)


class timed:
    """Context manager measuring a probe. ``with timed() as t: ...; t.ms``."""

    __slots__ = ("_start", "ms")

    def __init__(self) -> None:
        self.ms = 0.0

    def __enter__(self) -> timed:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.ms = (time.perf_counter() - self._start) * 1000.0


def first(rows: list[dict[str, Any]], default: dict[str, Any] | None = None) -> dict[str, Any]:
    return rows[0] if rows else (default or {})


def num(value: Any) -> float | None:
    """Coerce a CIM value to a float, tolerating the strings CIM sometimes returns."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None
