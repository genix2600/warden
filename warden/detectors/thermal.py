"""Thermal and throttling detection.

This detector deliberately does not key off temperature. Degrees are a proxy for
the thing users actually experience -- a machine that has gone slow -- and on
most consumer laptops the degrees are not available at all. What *is* always
available is the delivered clock against the rated clock, and that measures the
consequence directly: a processor pinned at full load that can only sustain 60%
of its rated frequency is being held back by heat, whether or not anything on
the machine will admit to a number in Celsius.

The detector therefore requires two things together before it says a word:
sustained load, and collapsed delivered performance. Either alone is normal. A
temperature reading, when one exists, is folded in as corroboration and raises
confidence -- it is never the trigger.

It also separates the two causes that have completely different answers:

* a single runaway process is generating the heat -- a software problem, and the
  answer is about that process;
* nothing in particular is running unusually and the machine still cannot hold
  its clocks -- a cooling problem, which no command can fix.

Only the second routes to servicing, and the fact that distinguishes them is
recorded in ``facts`` so the reasoner cannot skip the distinction.
"""

from __future__ import annotations

from typing import Any

from warden.config import THRESHOLDS, Thresholds
from warden.contracts import Observation, Severity, Symptom
from warden.detectors.base import Detector, mean
from warden.store import ObservationStore, as_dict, as_float, as_list


class ThermalThrottleDetector(Detector):
    id = "thermal.throttle"
    raises = ("THERMAL.SUSTAINED_THROTTLE", "THERMAL.HIGH_TEMPERATURE")

    def __init__(self, thresholds: Thresholds = THRESHOLDS) -> None:
        self.t = thresholds

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        window = self.t.thermal_window_s
        load = store.numeric_series("cpu.busy_pct", window)
        performance = store.numeric_series("cpu.performance_pct", window)
        temps = store.numeric_series("thermal.cpu_c", window)

        if len(load) < self.t.thermal_min_samples or len(performance) < self.t.thermal_min_samples:
            return []  # not enough history to call anything sustained

        mean_load = mean(load) or 0.0
        mean_perf = mean(performance) or 100.0
        min_perf = min(performance)
        max_temp = max(temps) if temps else None

        context = self._context(store, mean_load, mean_perf, min_perf, max_temp, window)

        symptoms: list[Symptom] = []
        under_load = mean_load >= self.t.sustained_load_pct
        throttling = mean_perf <= self.t.throttle_performance_pct

        if under_load and throttling:
            severe = mean_perf <= self.t.severe_throttle_performance_pct
            symptoms.append(
                self.symptom(
                    "THERMAL.SUSTAINED_THROTTLE",
                    severity=Severity.CRITICAL if severe else Severity.WARN,
                    title=(
                        "The processor is being held well below its rated speed"
                        if severe
                        else "The processor is running below its rated speed under load"
                    ),
                    detail=(
                        f"Over the last {window:.0f}s the processor averaged "
                        f"{mean_load:.0f}% busy while delivering only {mean_perf:.0f}% of its "
                        f"rated clock (lowest {min_perf:.0f}%)."
                        + (f" Peak temperature {max_temp:.0f} C." if max_temp else "")
                    ),
                    facts=context,
                    evidence=self._evidence(store, window),
                )
            )

        if (
            max_temp is not None
            and max_temp >= self.t.high_temperature_c
            and not any(s.code == "THERMAL.SUSTAINED_THROTTLE" for s in symptoms)
        ):
            symptoms.append(
                self.symptom(
                    "THERMAL.HIGH_TEMPERATURE",
                    severity=(
                        Severity.CRITICAL
                        if max_temp >= self.t.critical_temperature_c
                        else Severity.WARN
                    ),
                    title=f"Running hot at {max_temp:.0f} C",
                    detail=(
                        f"Peak sensor reading {max_temp:.0f} C over {window:.0f}s while the "
                        f"processor held {mean_perf:.0f}% of rated clock."
                    ),
                    facts=context,
                    evidence=self._evidence(store, window),
                )
            )
        return symptoms

    def _context(
        self,
        store: ObservationStore,
        mean_load: float,
        mean_perf: float,
        min_perf: float,
        max_temp: float | None,
        window: float,
    ) -> dict[str, Any]:
        clock = as_dict(store.value("cpu.clock"))
        provider = as_dict(store.value("thermal.provider"))
        fans = as_list(store.value("thermal.fan_rpm"))
        processes = as_list(store.value("sys.top_processes"))

        top = as_dict(processes[0]) if processes else {}
        top_share = as_float(top.get("cpu_percent")) or 0.0
        runaway = top_share >= self.t.runaway_process_pct

        fan_rpms = [rpm for f in fans if (rpm := as_float(as_dict(f).get("rpm"))) is not None]
        max_fan = max(fan_rpms, default=None)

        return {
            "window_s": window,
            "mean_load_pct": mean_load,
            "mean_performance_pct": mean_perf,
            "min_performance_pct": min_perf,
            "clock": clock,
            "max_temperature_c": max_temp,
            "temperature_available": max_temp is not None,
            "temperature_source": provider.get("active"),
            "temperature_source_tier": provider.get("tier"),
            "fan_rpm_max": max_fan,
            "fan_data_available": bool(fan_rpms),
            "busiest_process": top.get("name"),
            "busiest_process_pct": top_share,
            # The two facts the routing decision turns on. Named explicitly so a
            # reasoner cannot reach a servicing verdict without confronting the
            # possibility that a program is simply working hard.
            "explained_by_running_software": runaway,
            "cooling_suspect": (not runaway)
            and mean_perf <= self.t.severe_throttle_performance_pct,
        }

    @staticmethod
    def _evidence(store: ObservationStore, window: float) -> list[Observation | None]:
        evidence: list[Observation | None] = []
        for source in ("cpu.performance_pct", "cpu.busy_pct", "thermal.cpu_c"):
            history = store.history(source, within_s=window)
            evidence.extend(history[-2:])
        evidence.append(store.latest("cpu.clock"))
        evidence.append(store.latest("thermal.provider"))
        evidence.append(store.latest("sys.top_processes"))
        return evidence
