"""Temperature, and what to do when the machine will not tell you the temperature.

CPU temperature is the hardest genuinely-useful signal to obtain on consumer
Windows. There is no supported, universal API for it. ``MSAcpi_ThermalZoneTemperature``
is optional in the ACPI spec and most laptop vendors do not implement it;
everything that does work reads model-specific hardware registers and therefore
needs a kernel driver and an elevated process.

So this collector is a chain of providers, strongest first, and it reports which
one answered along with a confidence value the rest of the system respects:

  tier 1  LibreHardwareMonitor via pythonnet -- real per-core and package
          sensors, plus fan RPM. Needs the library present and admin rights.
  tier 2  the root/OpenHardwareMonitor WMI namespace, if that tool is running.
  tier 3  ACPI thermal zones. Present on some machines, absent on many.
  tier 4  throttle inference.

Tier 4 deserves a word, because it is the one that always works. Windows exposes
the processor's current clock against its rated maximum, and a performance
percentage, through CIM classes that need no driver and no elevation. A CPU held
at full load whose delivered frequency has collapsed to 60% of rated is being
throttled -- and sustained throttling under load is the *thing we actually care
about*, of which a temperature reading is only a proxy. A machine that reports
94 degrees and holds full clocks is working as designed. A machine that reports
nothing at all but has lost a third of its clock speed under load has a cooling
problem we can evidence without a single sensor.

That is why the thermal detector fuses both rather than keying off degrees.

One trap, found by measuring rather than by reading documentation:
``Win32_Processor.CurrentClockSpeed`` looks like the obvious source for that
ratio and is useless. On the development machine it reported exactly
``MaxClockSpeed`` at idle and through a three-minute all-core burn alike --
Windows hands back the rated base clock, not the delivered one. It is still
collected, because it does move on other hardware and is meaningful context
where it does, but no decision is keyed on it. ``PercentProcessorPerformance``
from the performance-counter class is the signal that actually varies. See
docs/calibration.md.
"""

from __future__ import annotations

import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from warden.collectors.base import Collector, first, num, timed
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult
from warden.paths import resource_path
from warden.winenv import is_admin

log = logging.getLogger(__name__)

VENDOR_DIR = resource_path("vendor")
LHM_DLL = VENDOR_DIR / "LibreHardwareMonitorLib.dll"

_ACPI_ZONES = json_pipeline(
    "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
    "-ErrorAction Stop | Select-Object InstanceName,CurrentTemperature"
)
_OHM_SENSORS = json_pipeline(
    "Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor "
    "-ErrorAction Stop | Where-Object { $_.SensorType -eq 'Temperature' } | "
    "Select-Object Name,Value,Parent"
)
_CLOCKS = json_pipeline(
    "Get-CimInstance Win32_Processor | "
    "Select-Object Name,MaxClockSpeed,CurrentClockSpeed,LoadPercentage,NumberOfCores"
)
_PERF = json_pipeline(
    "Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation "
    "-Filter \"Name='_Total'\" | "
    "Select-Object PercentProcessorTime,PercentProcessorPerformance,ProcessorFrequency"
)


@dataclass(frozen=True, slots=True)
class TempReading:
    label: str
    celsius: float


class ProviderUnavailable(RuntimeError):
    """This provider cannot answer on this machine, and says why in plain words."""


class ThermalProvider(ABC):
    id: str
    tier: int
    mechanism: Mechanism
    confidence: float
    needs: str

    @abstractmethod
    def read(self) -> tuple[list[TempReading], list[TempReading], str]:
        """Return (temperatures, fan readings, probe description).

        Fan readings reuse ``TempReading`` with ``celsius`` carrying RPM; the
        shape is identical and a second near-identical dataclass would earn
        nothing.
        """

    def close(self) -> None:  # noqa: B027 - an optional hook, deliberately not abstract
        """Only the .NET provider holds anything that needs releasing."""


class LibreHardwareMonitorProvider(ThermalProvider):
    """Real sensors. Needs vendor/LibreHardwareMonitorLib.dll and elevation.

    The library is MPL-2.0 and deliberately not vendored into this repository;
    ``scripts/fetch-sensors.ps1`` pulls it from NuGet. Without it Warden loses
    exact degrees and falls through to the tiers below -- it does not lose the
    ability to diagnose overheating.
    """

    id = "librehardwaremonitor"
    tier = 1
    mechanism = Mechanism.DOTNET
    confidence = 1.0
    needs = "vendor/LibreHardwareMonitorLib.dll and administrator rights"

    def __init__(self) -> None:
        self._computer = None
        self._sensor_type = None

    def _ensure(self) -> None:
        if self._computer is not None:
            return
        if not LHM_DLL.exists():
            raise ProviderUnavailable(f"{LHM_DLL.name} not present; run scripts/fetch-sensors.ps1")
        if not is_admin():
            raise ProviderUnavailable(
                "hardware sensor access needs an elevated process; "
                "Warden is running as a standard user"
            )
        try:
            import clr  # type: ignore[import-untyped]  # provided by pythonnet
        except ImportError as exc:
            raise ProviderUnavailable(
                "pythonnet is not installed (pip install '.[sensors]')"
            ) from exc

        try:
            clr.AddReference(str(LHM_DLL))
            from LibreHardwareMonitor.Hardware import (  # type: ignore[import-not-found]
                Computer,
                SensorType,
            )

            computer = Computer()
            computer.IsCpuEnabled = True
            computer.IsGpuEnabled = True
            computer.IsMotherboardEnabled = True
            computer.IsStorageEnabled = True
            computer.Open()
        except Exception as exc:
            raise ProviderUnavailable(f"could not open sensor library: {exc}") from exc
        self._computer = computer
        self._sensor_type = SensorType

    def read(self) -> tuple[list[TempReading], list[TempReading], str]:
        self._ensure()
        assert self._computer is not None and self._sensor_type is not None
        temps: list[TempReading] = []
        fans: list[TempReading] = []
        for hardware in self._computer.Hardware:
            hardware.Update()
            for sub in hardware.SubHardware:
                sub.Update()
            for sensor in hardware.Sensors:
                if sensor.Value is None:
                    continue
                label = f"{hardware.Name}/{sensor.Name}"
                if sensor.SensorType == self._sensor_type.Temperature:
                    temps.append(TempReading(label, float(sensor.Value)))
                elif sensor.SensorType == self._sensor_type.Fan:
                    fans.append(TempReading(label, float(sensor.Value)))
        if not temps:
            raise ProviderUnavailable("sensor library opened but exposed no temperatures")
        return temps, fans, "LibreHardwareMonitorLib Computer.Hardware[*].Sensors"

    def close(self) -> None:
        if self._computer is not None:
            with contextlib.suppress(Exception):
                self._computer.Close()
            self._computer = None


class OpenHardwareMonitorWmiProvider(ThermalProvider):
    id = "ohm_wmi"
    tier = 2
    mechanism = Mechanism.CIM
    confidence = 0.9
    needs = "OpenHardwareMonitor or LibreHardwareMonitor running with WMI enabled"

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def read(self) -> tuple[list[TempReading], list[TempReading], str]:
        probe = "Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor"
        try:
            rows, _ = self._ps.run_json(_OHM_SENSORS)
        except (PowerShellError, PowerShellUnavailable) as exc:
            raise ProviderUnavailable(str(exc)) from exc
        temps = [
            TempReading(str(r.get("Name") or "?"), float(value))
            for r in as_rows(rows)
            if (value := num(r.get("Value"))) is not None
        ]
        if not temps:
            raise ProviderUnavailable("namespace present but reported no temperatures")
        return temps, [], probe


class AcpiThermalZoneProvider(ThermalProvider):
    id = "acpi_thermal_zone"
    tier = 3
    mechanism = Mechanism.CIM
    confidence = 0.7
    needs = "a firmware that implements the optional ACPI thermal zone class"

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def read(self) -> tuple[list[TempReading], list[TempReading], str]:
        probe = "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature"
        try:
            rows, _ = self._ps.run_json(_ACPI_ZONES)
        except (PowerShellError, PowerShellUnavailable) as exc:
            raise ProviderUnavailable(str(exc)) from exc
        temps: list[TempReading] = []
        for row in as_rows(rows):
            raw = num(row.get("CurrentTemperature"))
            if raw is None:
                continue
            # ACPI reports tenths of a Kelvin.
            celsius = raw / 10.0 - 273.15
            if -20.0 < celsius < 150.0:
                name = str(row.get("InstanceName") or "thermal zone").split("\\")[-1]
                temps.append(TempReading(name, round(celsius, 1)))
        if not temps:
            raise ProviderUnavailable("class exists but returned no plausible readings")
        return temps, [], probe


class ThermalCollector(Collector):
    id = "thermal"
    interval_s = 3.0
    description = "Package temperature where available, and clock-throttle evidence always."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge
        self._providers: list[ThermalProvider] = [
            LibreHardwareMonitorProvider(),
            OpenHardwareMonitorWmiProvider(bridge),
            AcpiThermalZoneProvider(bridge),
        ]
        self._active: ThermalProvider | None = None
        self._unavailable: dict[str, str] = {}

    def close(self) -> None:
        for provider in self._providers:
            provider.close()

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_temperature(result)
        self._probe_throttle(result)
        return result

    def _probe_temperature(self, result: ProbeResult) -> None:
        # Prefer whichever provider answered last time; only re-walk the chain
        # when it stops working. Sensor init is expensive and the answer is
        # stable for the lifetime of a session.
        order = (
            [self._active, *[p for p in self._providers if p is not self._active]]
            if self._active
            else list(self._providers)
        )
        for provider in order:
            assert provider is not None
            try:
                with timed() as t:
                    temps, fans, probe = provider.read()
            except ProviderUnavailable as exc:
                self._unavailable[provider.id] = str(exc)
                if self._active is provider:
                    self._active = None
                continue
            except Exception as exc:
                self._unavailable[provider.id] = f"unexpected: {exc}"
                continue

            self._active = provider
            self._unavailable.pop(provider.id, None)
            hottest = max(temps, key=lambda r: r.celsius)
            result.observations.append(
                self.observation(
                    "thermal.cpu_c",
                    ObservationKind.METRIC,
                    round(hottest.celsius, 1),
                    unit="C",
                    probe=probe,
                    mechanism=provider.mechanism,
                    elapsed_ms=t.ms,
                    confidence=provider.confidence,
                )
            )
            result.observations.append(
                self.observation(
                    "thermal.sensors",
                    ObservationKind.INVENTORY,
                    [{"label": r.label, "celsius": round(r.celsius, 1)} for r in temps],
                    unit="C",
                    probe=probe,
                    mechanism=provider.mechanism,
                    elapsed_ms=t.ms,
                    confidence=provider.confidence,
                )
            )
            if fans:
                result.observations.append(
                    self.observation(
                        "thermal.fan_rpm",
                        ObservationKind.METRIC,
                        [{"label": r.label, "rpm": round(r.celsius)} for r in fans],
                        unit="rpm",
                        probe=probe,
                        mechanism=provider.mechanism,
                        elapsed_ms=t.ms,
                        confidence=provider.confidence,
                    )
                )
            break

        result.observations.append(
            self.observation(
                "thermal.provider",
                ObservationKind.STATE,
                {
                    "active": self._active.id if self._active else None,
                    "tier": self._active.tier if self._active else None,
                    "unavailable": [
                        {"provider": p.id, "needs": p.needs, "why": self._unavailable[p.id]}
                        for p in self._providers
                        if p.id in self._unavailable
                    ],
                },
                probe="provider chain resolution",
                mechanism=Mechanism.REGISTRY if self._active is None else self._active.mechanism,
                elapsed_ms=0,
            )
        )

    def _probe_throttle(self, result: ProbeResult) -> None:
        """Always available, no driver, no elevation. The floor under tier 1-3."""
        script = "Get-CimInstance Win32_Processor"
        try:
            rows, ms = self._ps.run_json(_CLOCKS)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
        else:
            cpu = first(as_rows(rows))
            current = num(cpu.get("CurrentClockSpeed"))
            maximum = num(cpu.get("MaxClockSpeed"))
            ratio = round(100.0 * current / maximum, 1) if current and maximum else None
            result.observations.append(
                self.observation(
                    "cpu.clock",
                    ObservationKind.STATE,
                    {
                        "current_mhz": current,
                        "max_mhz": maximum,
                        "ratio_pct": ratio,
                        "load_pct": num(cpu.get("LoadPercentage")),
                        "model": cpu.get("Name"),
                    },
                    unit="MHz",
                    probe=script,
                    mechanism=Mechanism.CIM,
                    elapsed_ms=ms,
                )
            )

        script = "Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation"
        try:
            rows, ms = self._ps.run_json(_PERF)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        perf = first(as_rows(rows))
        performance = num(perf.get("PercentProcessorPerformance"))
        if performance is None:
            return
        result.observations.append(
            self.observation(
                "cpu.performance_pct",
                ObservationKind.METRIC,
                performance,
                unit="%",
                probe=script,
                mechanism=Mechanism.PDH,
                elapsed_ms=ms,
                # A derived signal, not a sensor read. Saying so here is what
                # lets the detector weight it correctly against a real thermistor.
                confidence=0.8,
            )
        )
        result.observations.append(
            self.observation(
                "cpu.busy_pct",
                ObservationKind.METRIC,
                num(perf.get("PercentProcessorTime")) or 0.0,
                unit="%",
                probe=script,
                mechanism=Mechanism.PDH,
                elapsed_ms=ms,
            )
        )
