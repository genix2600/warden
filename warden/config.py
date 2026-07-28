"""Every threshold Warden judges a machine by, in one reviewable place.

Thresholds scattered through detector code are unauditable: nobody can tell
whether "90" was measured or guessed. These were measured -- see
``docs/calibration.md`` for the run that produced them -- and they are collected
here so that changing the definition of "too hot" is a visible, single-line
diff rather than an archaeology exercise.

Values may be overridden from ``warden.local.toml`` for a specific machine
without editing source. That file is gitignored and, by design, has nowhere to
put a credential: it holds numbers only.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

LOCAL_CONFIG = Path("warden.local.toml")


@dataclass(frozen=True, slots=True)
class Thresholds:
    # -- thermal --------------------------------------------------------
    thermal_window_s: float = 45.0
    """How long a condition must persist before it counts as sustained. A laptop
    that throttles for three seconds during a video export is behaving; one that
    holds reduced clocks for the better part of a minute is not."""

    thermal_min_samples: int = 5
    """Refuse to conclude anything from fewer readings than this."""

    sustained_load_pct: float = 80.0
    """Mean processor busy percentage that qualifies as "under load". Below this,
    a low delivered clock means the machine is idling down, not throttling."""

    throttle_performance_pct: float = 85.0
    """Delivered clock as a percentage of rated, below which we call it
    throttling.

    Measured: a healthy i5-1135G7 laptop held 88-94% (mean 90.6) through three
    minutes at 100% on all cores. This line sits just under that floor, so it
    separates working-as-designed from genuine throttling without tripping on
    normal variation. A machine whose heatsink is blocked drops to 50-70% under
    the same load. See docs/calibration.md."""

    severe_throttle_performance_pct: float = 70.0
    """Below this, under load, the cooling system is not keeping up at all."""

    high_temperature_c: float = 90.0
    """Only used when a real sensor is available; ignored otherwise."""

    critical_temperature_c: float = 97.0

    runaway_process_pct: float = 55.0
    """A single process holding this share of the whole machine explains the heat
    by itself, and the answer is about that process rather than about cooling."""

    # -- storage --------------------------------------------------------
    disk_low_percent_used: float = 92.0
    disk_low_free_gb: float = 12.0
    """Both must be true. A 92%-full 4TB drive still has 300GB and is fine."""

    # -- network --------------------------------------------------------
    weak_signal_pct: float = 25.0

    def merged_with(self, overrides: dict[str, object]) -> Thresholds:
        known = {f.name for f in fields(self)}
        clean = {}
        for key, value in overrides.items():
            if key not in known:
                log.warning("ignoring unknown threshold %r in %s", key, LOCAL_CONFIG)
                continue
            if not isinstance(value, int | float):
                log.warning("ignoring non-numeric threshold %r", key)
                continue
            clean[key] = float(value)
        return Thresholds(**{**asdict(self), **clean})


def load_thresholds(path: Path = LOCAL_CONFIG) -> Thresholds:
    defaults = Thresholds()
    if not path.exists():
        return defaults
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s, using defaults: %s", path, exc)
        return defaults
    section = data.get("thresholds", {})
    if not isinstance(section, dict):
        return defaults
    log.info("applying %d threshold override(s) from %s", len(section), path)
    return defaults.merged_with(section)


THRESHOLDS = load_thresholds()
