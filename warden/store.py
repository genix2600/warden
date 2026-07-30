"""In-memory history of everything the collectors have seen.

Bounded by both age and count, because Warden runs for hours on a laptop and an
unbounded list of readings would be its own performance problem. Ten minutes is
enough for every detector here -- the longest window any of them looks at is
about a minute -- and enough for the UI to draw a sparkline.

Retrieval by id matters as much as retrieval by source: a diagnosis cites
observation ids, and the UI resolves them back to the full reading, with its
provenance, when the user asks to see the evidence.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import timedelta

from pydantic import JsonValue

from warden.contracts import Observation, utcnow

DEFAULT_RETENTION_S = 600.0
DEFAULT_MAX_PER_SOURCE = 400


# -- reading heterogeneous payloads safely ---------------------------------
#
# An ``Observation.value`` is a ``JsonValue`` because collectors genuinely
# return different shapes: a float, a state object, a list of devices. Code that
# consumes them tends to reach straight for ``value["state"]`` on the strength of
# knowing what the collector produces -- which is a convention, not a guarantee,
# and turns into an AttributeError the day a probe returns something unexpected
# on someone else's machine.
#
# These three coercions make the narrowing explicit and total. They never raise:
# a wrong-shaped payload degrades to the default, the detector concludes nothing,
# and the agent stays quiet rather than crashing the tick.


def as_dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def as_list(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def as_float(value: JsonValue, default: float | None = None) -> float | None:
    """Numeric coercion that tolerates the strings CIM sometimes returns."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


class ObservationStore:
    """Thread-safe. Collectors write from the pool; the API reads from the loop."""

    def __init__(
        self,
        retention_s: float = DEFAULT_RETENTION_S,
        max_per_source: int = DEFAULT_MAX_PER_SOURCE,
    ) -> None:
        self._retention = timedelta(seconds=retention_s)
        self._by_source: dict[str, deque[Observation]] = defaultdict(
            lambda: deque(maxlen=max_per_source)
        )
        self._by_id: dict[str, Observation] = {}
        self._lock = threading.RLock()

    def ingest(self, observations: list[Observation]) -> None:
        with self._lock:
            for obs in observations:
                self._by_source[obs.source].append(obs)
                self._by_id[obs.id] = obs
            self._evict()

    def _evict(self) -> None:
        cutoff = utcnow() - self._retention
        live: set[str] = set()
        for series in self._by_source.values():
            while series and series[0].captured_at < cutoff:
                series.popleft()
            live.update(o.id for o in series)
        if len(self._by_id) > len(live):
            self._by_id = {k: v for k, v in self._by_id.items() if k in live}

    # -- reads -------------------------------------------------------------

    def latest(self, source: str, max_age_s: float | None = None) -> Observation | None:
        """Most recent reading from a source, optionally refusing stale ones.

        ``max_age_s`` exists for verification, and the distinction it draws is
        the difference between an honest answer and a dangerous one. A caller
        that gets ``None`` because a source was never read reports "could not
        tell". A caller that gets a ten-minute-old reading has no idea it is
        holding history, and history is systematically misleading here: the last
        reading before a fault is by definition the last *healthy* one. Asking
        "is the adapter connected?" and being handed the sample from before it
        dropped answers yes, forever.

        Retention is 600 seconds, so without this the window for that mistake is
        ten minutes wide.
        """
        with self._lock:
            series = self._by_source.get(source)
            observation = series[-1] if series else None
        if observation is None or max_age_s is None:
            return observation
        if observation.captured_at < utcnow() - timedelta(seconds=max_age_s):
            return None
        return observation

    def value(self, source: str, default: JsonValue = None) -> JsonValue:
        obs = self.latest(source)
        return obs.value if obs is not None else default

    def field(self, source: str, key: str, default: JsonValue = None) -> JsonValue:
        """Read one key out of a STATE observation whose value is an object."""
        value = self.value(source)
        if isinstance(value, dict):
            return value.get(key, default)
        return default

    def by_id(self, observation_id: str) -> Observation | None:
        with self._lock:
            return self._by_id.get(observation_id)

    def history(self, source: str, within_s: float | None = None) -> list[Observation]:
        with self._lock:
            series = list(self._by_source.get(source, ()))
        if within_s is None:
            return series
        cutoff = utcnow() - timedelta(seconds=within_s)
        return [o for o in series if o.captured_at >= cutoff]

    def numeric_series(self, source: str, within_s: float) -> list[float]:
        return [
            float(o.value)
            for o in self.history(source, within_s)
            if isinstance(o.value, int | float) and not isinstance(o.value, bool)
        ]

    def last_where(
        self, source: str, key: str, equals: JsonValue, within_s: float = 300.0
    ) -> Observation | None:
        """Most recent observation whose ``value[key]`` matched.

        This is how the wireless playbook learns which network to reconnect to:
        not from a saved-profile list, which is localised and may hold a dozen
        stale entries, but from the last moment Warden itself watched the
        machine associated to something. Its own history is the better source.
        """
        for obs in reversed(self.history(source, within_s)):
            if isinstance(obs.value, dict) and obs.value.get(key) == equals:
                return obs
        return None

    def snapshot(self) -> dict[str, Observation]:
        """Latest reading per source. What the UI renders as live telemetry."""
        with self._lock:
            return {source: series[-1] for source, series in self._by_source.items() if series}

    def sources(self) -> list[str]:
        with self._lock:
            return sorted(self._by_source)
