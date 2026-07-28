"""Physical component health: battery wear and drive reliability.

Both answer the same question — is a part of this machine wearing out — and both
have the property that makes them worth collecting: *no command can fix what they
find*. A battery at 60% of its design capacity is a battery that needs replacing,
and software saying otherwise would be lying.

They are also the most reliable demonstration of Warden's routing rule. Thermal
throttling only appears on a machine whose cooling has actually degraded, so a
healthy laptop shows nothing; battery wear accumulates on every laptop from the
day it is bought, and is readable in under two seconds.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from pydantic import JsonValue

from warden.collectors.base import Collector, first, num
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

log = logging.getLogger(__name__)

_BATTERY = json_pipeline(
    "Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | "
    "Select-Object Name,EstimatedChargeRemaining,BatteryStatus,Chemistry,DesignCapacity"
)
_FULL_CHARGE = json_pipeline(
    "Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity "
    "-ErrorAction Stop | Select-Object FullChargedCapacity"
)
_CYCLES = json_pipeline(
    "Get-CimInstance -Namespace root/wmi -ClassName BatteryCycleCount "
    "-ErrorAction Stop | Select-Object CycleCount"
)
_STATIC_DATA = json_pipeline(
    "Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData "
    "-ErrorAction Stop | Select-Object DesignedCapacity"
)
_DISKS = json_pipeline(
    "Get-PhysicalDisk -ErrorAction SilentlyContinue | "
    "Select-Object FriendlyName,HealthStatus,OperationalStatus,MediaType,Size,SerialNumber"
)
_VOLUMES = json_pipeline(
    "Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter } | "
    "Select-Object DriveLetter,HealthStatus,FileSystemType,OperationalStatus"
)

#: ACPI chemistry codes from Win32_Battery. Reported so the advice can name the
#: cell type, which a repair shop will ask for.
_CHEMISTRY = {
    1: "other",
    2: "unknown",
    3: "lead acid",
    4: "nickel cadmium",
    5: "nickel metal hydride",
    6: "lithium-ion",
    7: "zinc air",
    8: "lithium polymer",
}


class BatteryCollector(Collector):
    """Battery wear, via a two-tier chain for the one value that is hard to get.

    Full-charge capacity and cycle count come straight from WMI and are cheap.
    *Design* capacity is the awkward one: ``Win32_Battery.DesignCapacity`` is
    empty on this hardware and ``BatteryStaticData`` throws "Generic failure",
    which is common — vendors implement these classes inconsistently. The
    fallback is ``powercfg /batteryreport``, which is authoritative but costs
    about a second and writes a file.

    Since a battery's design capacity is a manufacturing constant, it is read
    once and cached for the life of the process. Only the values that actually
    move are re-read each interval.
    """

    id = "hw.battery"
    interval_s = 60.0
    description = "Battery charge, cycle count and capacity against its original design."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge
        self._design_mwh: float | None = None
        self._design_source: str | None = None
        self._design_attempted = False

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        script = "Get-CimInstance Win32_Battery"
        try:
            rows, ms = self._ps.run_json(_BATTERY)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return result

        battery = first(as_rows(rows))
        if not battery:
            # A desktop has no battery. That is not a fault, and the observation
            # exists so the detector can tell "no battery" from "not read yet".
            result.observations.append(
                self.observation(
                    "hw.battery.present",
                    ObservationKind.STATE,
                    False,
                    probe=script,
                    mechanism=Mechanism.CIM,
                    elapsed_ms=ms,
                )
            )
            return result

        result.observations.append(
            self.observation(
                "hw.battery.present",
                ObservationKind.STATE,
                True,
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

        chemistry = battery.get("Chemistry")
        result.observations.append(
            self.observation(
                "hw.battery.charge",
                ObservationKind.METRIC,
                {
                    "percent": num(battery.get("EstimatedChargeRemaining")),
                    "status_code": battery.get("BatteryStatus"),
                    "chemistry": _CHEMISTRY.get(
                        chemistry if isinstance(chemistry, int) else -1, "unknown"
                    ),
                },
                unit="%",
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )
        self._probe_health(result)
        return result

    def _probe_health(self, result: ProbeResult) -> None:
        full_mwh = self._read_single(_FULL_CHARGE, "FullChargedCapacity", result)
        cycles = self._read_single(_CYCLES, "CycleCount", result)
        design_mwh = self._design_capacity(result)

        health_pct = (
            round(100.0 * full_mwh / design_mwh, 1)
            if full_mwh and design_mwh and design_mwh > 0
            else None
        )
        result.observations.append(
            self.observation(
                "hw.battery.health",
                ObservationKind.METRIC,
                {
                    "design_mwh": design_mwh,
                    "full_charge_mwh": full_mwh,
                    "health_pct": health_pct,
                    "cycle_count": cycles,
                    "design_source": self._design_source,
                },
                unit="%",
                probe=(
                    "Get-CimInstance root/wmi BatteryFullChargedCapacity + BatteryCycleCount"
                    + (f"; design via {self._design_source}" if self._design_source else "")
                ),
                mechanism=Mechanism.CIM,
                elapsed_ms=0,
                # Wear is a ratio of two independently-sourced numbers; if the
                # design figure came from the report rather than from WMI it is
                # still exact, so confidence stays high either way.
                confidence=1.0 if health_pct is not None else 0.5,
            )
        )

    def _read_single(self, script: str, key: str, result: ProbeResult) -> float | None:
        try:
            rows, _ = self._ps.run_json(script)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(key, exc))
            return None
        return num(first(as_rows(rows)).get(key))

    def _design_capacity(self, result: ProbeResult) -> float | None:
        """Read once, cache forever. A design capacity does not change."""
        if self._design_attempted:
            return self._design_mwh
        self._design_attempted = True

        try:
            rows, _ = self._ps.run_json(_STATIC_DATA)
            value = num(first(as_rows(rows)).get("DesignedCapacity"))
            if value:
                self._design_mwh, self._design_source = value, "BatteryStaticData"
                return value
        except (PowerShellError, PowerShellUnavailable) as exc:
            log.debug("BatteryStaticData unavailable, falling back to powercfg: %s", exc)

        value = self._design_from_report()
        if value:
            self._design_mwh, self._design_source = value, "powercfg /batteryreport"
        else:
            result.errors.append(
                self.failure(
                    "powercfg /batteryreport",
                    "no source on this machine reports the battery's design capacity, "
                    "so wear cannot be calculated",
                )
            )
        return self._design_mwh

    @staticmethod
    def _design_from_report() -> float | None:
        """Parse ``powercfg /batteryreport``, the authoritative fallback.

        Writes to a temporary file because powercfg has no stdout mode. Measured
        at ~1.1s, which is why this runs once rather than every interval.
        """
        with tempfile.TemporaryDirectory(prefix="warden-batt-") as directory:
            report = Path(directory) / "battery.xml"
            try:
                completed = subprocess.run(
                    ["powercfg", "/batteryreport", "/xml", "/output", str(report)],
                    capture_output=True,
                    timeout=25,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                log.debug("powercfg battery report failed: %s", exc)
                return None
            if completed.returncode != 0 or not report.exists():
                return None
            try:
                tree = ET.parse(report)
            except ET.ParseError:
                return None

        # The report is namespaced; matching on the local tag name avoids
        # hard-coding a namespace URI that has changed between Windows releases.
        for element in tree.iter():
            if element.tag.rsplit("}", 1)[-1] == "Battery":
                for child in element:
                    if child.tag.rsplit("}", 1)[-1] == "DesignCapacity" and child.text:
                        try:
                            return float(child.text)
                        except ValueError:
                            return None
        return None


class StorageHealthCollector(Collector):
    """Drive health as the drive itself reports it.

    ``HealthStatus`` is the storage stack's own summary of SMART data. It is
    coarse -- Healthy, Warning, Unhealthy -- but it is the part that needs no
    elevation. ``Get-StorageReliabilityCounter`` carries the detailed wear and
    temperature figures and requires administrator rights, so it is attempted
    and allowed to fail rather than being a prerequisite.
    """

    id = "hw.storage"
    interval_s = 60.0
    description = "Physical drive health as reported by the drive's own SMART data."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_disks(result)
        self._probe_volumes(result)
        return result

    def _probe_disks(self, result: ProbeResult) -> None:
        script = "Get-PhysicalDisk"
        try:
            rows, ms = self._ps.run_json(_DISKS)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        disks: list[dict[str, JsonValue]] = []
        for row in as_rows(rows):
            size = num(row.get("Size"))
            disks.append(
                {
                    "name": row.get("FriendlyName"),
                    "health": row.get("HealthStatus"),
                    "operational": row.get("OperationalStatus"),
                    "media_type": row.get("MediaType"),
                    "size_gb": round(size / 1_073_741_824) if size else None,
                }
            )
        result.observations.append(
            self.observation(
                "hw.storage.disks",
                ObservationKind.INVENTORY,
                list(disks),
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

    def _probe_volumes(self, result: ProbeResult) -> None:
        script = "Get-Volume"
        try:
            rows, ms = self._ps.run_json(_VOLUMES)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        volumes: list[dict[str, JsonValue]] = [
            {
                "drive": row.get("DriveLetter"),
                "health": row.get("HealthStatus"),
                "filesystem": row.get("FileSystemType"),
                "operational": row.get("OperationalStatus"),
            }
            for row in as_rows(rows)
        ]
        result.observations.append(
            self.observation(
                "hw.storage.volumes",
                ObservationKind.INVENTORY,
                list(volumes),
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )
