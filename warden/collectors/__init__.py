"""Collector registry and the scheduler that runs them.

Collectors declare their own poll interval and are dispatched on a small thread
pool. Two rules hold the layer together:

* a collector that throws is a bug, but the tick survives it anyway -- failures
  become ``ProbeError`` values in the result and the other collectors still
  report;
* a slow collector delays only itself. The event-log probe takes a second or
  more, and it must never make the wireless probe late.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from warden.collectors.audit import AuditSettingsCollector
from warden.collectors.base import Collector
from warden.collectors.hardware import BatteryCollector, StorageHealthCollector
from warden.collectors.netconfig import NetConfigCollector
from warden.collectors.network import ConnectivityCollector, WifiCollector
from warden.collectors.privacy import PrivacyCollector
from warden.collectors.psbridge import PowerShellBridge
from warden.collectors.services import ServiceCollector
from warden.collectors.system import ProcessCollector, SystemCollector
from warden.collectors.thermal import ThermalCollector
from warden.collectors.timesync import TimeSyncCollector
from warden.collectors.windows import DeviceCollector, EventLogCollector
from warden.contracts import ProbeResult

log = logging.getLogger(__name__)

__all__ = [
    "BatteryCollector",
    "Collector",
    "CollectorHost",
    "ConnectivityCollector",
    "DeviceCollector",
    "EventLogCollector",
    "NetConfigCollector",
    "PrivacyCollector",
    "ProcessCollector",
    "ServiceCollector",
    "StorageHealthCollector",
    "SystemCollector",
    "ThermalCollector",
    "TimeSyncCollector",
    "WifiCollector",
    "build_default_collectors",
]


def build_default_collectors(bridge: PowerShellBridge) -> list[Collector]:
    return [
        SystemCollector(),
        ProcessCollector(),
        WifiCollector(bridge),
        ConnectivityCollector(bridge),
        ThermalCollector(bridge),
        DeviceCollector(bridge),
        EventLogCollector(bridge),
        BatteryCollector(bridge),
        StorageHealthCollector(bridge),
        ServiceCollector(bridge),
        PrivacyCollector(bridge),
        NetConfigCollector(bridge),
        TimeSyncCollector(bridge),
        AuditSettingsCollector(bridge),
    ]


class CollectorHost:
    def __init__(
        self,
        collectors: list[Collector] | None = None,
        bridge: PowerShellBridge | None = None,
    ) -> None:
        self.bridge = bridge or PowerShellBridge()
        self.collectors = (
            collectors if collectors is not None else build_default_collectors(self.bridge)
        )
        self._last_run: dict[str, float] = {}
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="collector")
        self.warmup_ms = 0.0

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.collectors]

    def warmup(self) -> float:
        """Pay the one-off costs once, before monitoring starts.

        Two kinds: PowerShell autoloading its networking modules (~6s the first
        time), and collectors that measure a rate needing a baseline sample
        before their first reading means anything.
        """
        started = time.monotonic()
        self.bridge.warmup()
        for collector in self.collectors:
            try:
                collector.warmup()
            except Exception:
                log.warning("collector %s failed to warm up", collector.id, exc_info=True)
        self.warmup_ms = (time.monotonic() - started) * 1000.0
        log.info("collector warmup finished in %.0fms", self.warmup_ms)
        return self.warmup_ms

    def due(self, now: float | None = None) -> list[Collector]:
        now = now if now is not None else time.monotonic()
        return [c for c in self.collectors if now - self._last_run.get(c.id, -1e9) >= c.interval_s]

    def run(self, collectors: list[Collector]) -> ProbeResult:
        """Probe the given collectors concurrently and merge their results."""
        if not collectors:
            return ProbeResult()
        now = time.monotonic()
        futures = {c.id: self._pool.submit(self._guarded, c) for c in collectors}
        merged = ProbeResult()
        for collector in collectors:
            self._last_run[collector.id] = now
            merged = merged + futures[collector.id].result()
        return merged

    def run_ids(self, ids: list[str]) -> ProbeResult:
        """Force-run named collectors regardless of their schedule.

        Used by the verifier: after an action runs, the specific probes that can
        prove or disprove success are re-read immediately rather than waiting for
        their next natural tick.
        """
        wanted = {c.id: c for c in self.collectors}
        return self.run([wanted[i] for i in ids if i in wanted])

    @staticmethod
    def _guarded(collector: Collector) -> ProbeResult:
        try:
            return collector.probe()
        except Exception as exc:
            log.exception("collector %s raised", collector.id)
            return ProbeResult(errors=[collector.failure(collector.id, exc)])

    def close(self) -> None:
        for collector in self.collectors:
            try:
                collector.close()
            except Exception:
                log.warning("collector %s failed to close", collector.id, exc_info=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.bridge.close()
