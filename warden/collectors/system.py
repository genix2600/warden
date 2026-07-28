"""CPU, memory, disk and process load, via psutil.

The cheapest collector and the one that runs most often, because almost every
other diagnosis needs load as context: 94 degrees under a full compile is
expected behaviour, 94 degrees at idle is a fault.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Protocol

import psutil
from pydantic import JsonValue

from warden.collectors.base import Collector, timed
from warden.contracts import Mechanism, ObservationKind, ProbeResult
from warden.store import as_float

_PROC_FIELDS = ("pid", "name", "cpu_percent", "memory_info")


class CpuTimes(Protocol):
    """The shape of a ``psutil.cpu_times()`` sample that this module relies on.

    psutil returns a platform-specific named tuple whose field list differs by
    operating system, so there is no concrete type to annotate against. Naming
    the two properties actually used -- iterable of floats, plus ``idle`` --
    documents the dependency and lets the type checker verify the arithmetic
    instead of being silenced with an ignore comment.
    """

    # A read-only property rather than a bare attribute: psutil returns a named
    # tuple, whose fields are immutable, and a settable protocol member would
    # not match one.
    @property
    def idle(self) -> float: ...

    def __iter__(self) -> Iterator[float]: ...


def _busy_percent(previous: CpuTimes, current: CpuTimes) -> float | None:
    """Percentage of a CPU's time that was not idle, between two samples."""
    delta_total = sum(current) - sum(previous)
    if delta_total <= 0:
        return None
    delta_idle = current.idle - previous.idle
    return round(100.0 * (1.0 - delta_idle / delta_total), 1)


class SystemCollector(Collector):
    id = "sys.perf"
    interval_s = 2.0
    description = "Processor load, memory pressure and disk headroom."

    def __init__(self) -> None:
        # psutil's own ``cpu_percent`` keeps its baseline in *thread-local*
        # storage. Collectors are dispatched onto a thread pool, so the first
        # probe to land on each worker would silently report 0.0% -- which is
        # not a wrong-looking number, it is a plausible-looking wrong number,
        # the worst kind. Holding the previous CPU-time sample ourselves makes
        # the measurement independent of which thread happens to run it, and
        # lets us report the window the average was taken over.
        self._prev = psutil.cpu_times()
        self._prev_per_core = psutil.cpu_times(percpu=True)
        self._prev_at = time.monotonic()

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_cpu(result)
        self._probe_memory(result)
        self._probe_disks(result)

        with timed() as t:
            boot = psutil.boot_time()
        result.observations.append(
            self.observation(
                "sys.boot_time",
                ObservationKind.METRIC,
                boot,
                unit="epoch_s",
                probe="psutil.boot_time()",
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )
        return result

    def _probe_cpu(self, result: ProbeResult) -> None:
        with timed() as t:
            current = psutil.cpu_times()
            current_per_core = psutil.cpu_times(percpu=True)
        now = time.monotonic()
        window_s = now - self._prev_at

        overall = _busy_percent(self._prev, current)
        per_core = [
            _busy_percent(prev, cur)
            for prev, cur in zip(self._prev_per_core, current_per_core, strict=False)
        ]
        self._prev, self._prev_per_core, self._prev_at = current, current_per_core, now

        if overall is None:
            return  # two samples inside the same clock tick; nothing to report yet

        probe = f"psutil.cpu_times() delta over {window_s:.1f}s"
        result.observations.append(
            self.observation(
                "sys.cpu.percent",
                ObservationKind.METRIC,
                overall,
                unit="%",
                probe=probe,
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )
        result.observations.append(
            self.observation(
                "sys.cpu.per_core",
                ObservationKind.METRIC,
                [c for c in per_core if c is not None],
                unit="%",
                probe=f"psutil.cpu_times(percpu=True) delta over {window_s:.1f}s",
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )

    def _probe_memory(self, result: ProbeResult) -> None:
        with timed() as t:
            mem = psutil.virtual_memory()
        result.observations.append(
            self.observation(
                "sys.memory",
                ObservationKind.METRIC,
                {
                    "percent": mem.percent,
                    "available_mb": round(mem.available / 1_048_576),
                    "total_mb": round(mem.total / 1_048_576),
                },
                unit="%",
                probe="psutil.virtual_memory()",
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )

    def _probe_disks(self, result: ProbeResult) -> None:
        probe = "psutil.disk_partitions() + disk_usage()"
        with timed() as t:
            volumes: list[dict[str, JsonValue]] = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                except OSError:
                    continue  # empty card reader or optical drive; not a fault
                volumes.append(
                    {
                        "mount": part.mountpoint,
                        "fs": part.fstype,
                        "percent_used": usage.percent,
                        "free_gb": round(usage.free / 1_073_741_824, 1),
                        "total_gb": round(usage.total / 1_073_741_824, 1),
                    }
                )
        result.observations.append(
            self.observation(
                "sys.disk.volumes",
                ObservationKind.METRIC,
                list(volumes),
                probe=probe,
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )


class ProcessCollector(Collector):
    """Separated from ``sys.perf`` because it is two orders of magnitude slower.

    Enumerating processes on Windows opens a handle per PID; measured at ~3s for
    ~340 processes on the development machine, and the cost is in the walk, not
    in the fields requested. That is fine for context gathered every fifteen
    seconds and unacceptable inside a two-second loop, so it lives here with its
    own interval and its own pool slot. The orchestrator force-runs it when an
    incident opens, which is when "what is actually eating the CPU" matters.
    """

    id = "sys.processes"
    interval_s = 15.0
    description = "The busiest processes by CPU and resident memory."

    def warmup(self) -> None:
        """Establish each process's CPU baseline.

        ``Process.cpu_percent()`` is a delta since the previous call on that same
        process object, so the first reading for every process is 0.0 -- and
        psutil caches per-process state internally, so a fresh walk starts from
        nothing. Left unprimed, the first sample says the machine is completely
        idle no matter what is running, and the thermal detector reads that to
        mean "no program explains this heat", which flips a diagnosis from
        "handbrake.exe is working hard" to "your cooling has failed".

        Priming costs a few seconds, paid once, on a worker thread, at startup.
        """
        for process in psutil.process_iter(["cpu_percent"]):
            del process

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        probe = "psutil.process_iter(['name','cpu_percent','memory_info'])"
        cores = psutil.cpu_count() or 1
        with timed() as t:
            rows: list[dict[str, JsonValue]] = []
            for proc in psutil.process_iter(_PROC_FIELDS):
                try:
                    info = proc.info
                    mem = info.get("memory_info")
                    rows.append(
                        {
                            "pid": info["pid"],
                            "name": info.get("name") or "?",
                            # psutil reports per-process CPU against a single
                            # core, so a fully-busy 8-core box reads 800%.
                            # Normalising to whole-machine percentage is what a
                            # user expects Task Manager to show them.
                            "cpu_percent": round((info.get("cpu_percent") or 0.0) / cores, 1),
                            "rss_mb": round(mem.rss / 1_048_576) if mem else 0,
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue  # exited or protected; both are normal on Windows
            rows.sort(key=lambda r: as_float(r["cpu_percent"]) or 0.0, reverse=True)
        result.observations.append(
            self.observation(
                "sys.top_processes",
                ObservationKind.INVENTORY,
                list(rows[:6]),
                probe=probe,
                mechanism=Mechanism.PSUTIL,
                elapsed_ms=t.ms,
            )
        )
        return result
