"""Settings the audit examines: things that never change on their own.

These readings are not symptoms of anything. The machine is working. They are
configuration that was set once -- at the factory, by an installer, by a
technician years ago -- and has never been looked at since, and each one has a
measurable cost.

A long interval on purpose. A power-management flag does not move between polls,
and the audit runs on demand rather than on a timer, so paying for these every
two seconds would be waste with no reader.
"""

from __future__ import annotations

from typing import Any

from pydantic import JsonValue

from warden.collectors.base import Collector
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

#: Whether Windows is allowed to power down the wireless adapter to save energy.
#: A factory default on a very large number of laptops, invisible in every
#: consumer tool, and a direct cause of the intermittent "can't connect to this
#: network" disconnection Warden already demonstrates repairing. Reading it is
#: how the audit stops treating the symptom and names the cause.
_ADAPTER_POWER = json_pipeline(
    "Get-NetAdapter -Physical | Where-Object MediaType -eq 'Native 802.11' | "
    "ForEach-Object { $p = $_ | Get-NetAdapterPowerManagement -ErrorAction SilentlyContinue; "
    "[pscustomobject]@{ Name = $_.Name; "
    "AllowComputerToTurnOffDevice = "
    "if ($p) { [string]$p.AllowComputerToTurnOffDevice } else { $null } } }"
)

#: The scheduled optimisation task. On a solid-state drive the correct operation
#: is TRIM, not defragmentation; the schedule existing is not itself a fault, so
#: the check reads the drive type before saying anything.
_DEFRAG_TASK = json_pipeline(
    "Get-ScheduledTask -TaskPath '\\Microsoft\\Windows\\Defrag\\' "
    "-TaskName 'ScheduledDefrag' -ErrorAction SilentlyContinue | "
    "Select-Object TaskName,State"
)

#: The three places Windows records that it is waiting for a restart. Any one of
#: them is enough; a machine that has been waiting for weeks is one of the most
#: common causes of "my computer is being weird" and is reported by nothing the
#: user can see.
_CV = "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
_REBOOT_PENDING = (
    f"$cbs = Test-Path '{_CV}\\Component Based Servicing\\RebootPending'; "
    f"$wu = Test-Path '{_CV}\\WindowsUpdate\\Auto Update\\RebootRequired'; "
    "$ren = [bool]((Get-ItemProperty "
    "'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager' "
    "-Name PendingFileRenameOperations -ErrorAction SilentlyContinue)."
    "PendingFileRenameOperations); "
    "$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime; "
    "@{ servicing = $cbs; windows_update = $wu; file_renames = $ren; "
    "last_boot = $boot.ToString('o') } | ConvertTo-Json -Compress"
)


#: Third-party driver dates, deliberately excluding Microsoft's own.
#:
#: The naive version of this check is unusable. Windows ships pseudo-devices
#: whose drivers are genuinely dated 2006 and correctly never change: the WAN
#: Miniports alone would make every machine on earth report six ancient
#: "out of date" drivers. Filtering on the provider leaves the drivers a vendor
#: actually maintains.
#:
#: One CIM query rather than Get-PnpDeviceProperty per device. The per-device
#: version was correct and took longer than the bridge's whole timeout; this
#: returns the same information for every driver on the machine in 4.4s.
_DRIVER_DATES = json_pipeline(
    "Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue | "
    "Where-Object { $_.DriverProviderName -and $_.DriverDate -and "
    "$_.DriverProviderName -notlike 'Microsoft*' } | "
    "Select-Object DeviceName,DriverProviderName,DeviceClass,"
    "@{n='DriverDate';e={$_.DriverDate.ToString('o')}}"
)

#: The active power plan, the processor ceiling it applies on mains, and whether
#: this is a laptop. All three are needed together: a capped processor is a
#: misconfiguration on a desktop and a deliberate choice on a laptop, and Warden
#: has no business guessing which.
_POWER_PROFILE = (
    "$s = (powercfg /getactivescheme) -join ' '; "
    "$m = [regex]::Match($s, 'GUID:\s*([0-9a-f-]+)\s*\((.*?)\)'); "
    "$ac = (((powercfg /q SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX) | "
    "Select-String 'Current AC Power Setting') -replace '.*:\s*','').Trim(); "
    "$dc = (((powercfg /q SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX) | "
    "Select-String 'Current DC Power Setting') -replace '.*:\s*','').Trim(); "
    "$chassis = (Get-CimInstance Win32_SystemEnclosure).ChassisTypes; "
    "@{ scheme = $m.Groups[2].Value; scheme_guid = $m.Groups[1].Value; "
    "ac_max_pct = [Convert]::ToInt32($ac, 16); "
    "dc_max_pct = [Convert]::ToInt32($dc, 16); "
    "chassis = @($chassis)[0] } | ConvertTo-Json -Compress"
)

#: Programs that start with Windows, and whether the user has already turned any
#: of them off. Counted rather than judged: Warden does not know that somebody
#: wants their backup client to stop launching.
_STARTUP = (
    "$items = @(); "
    "foreach ($k in 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',"
    "'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run') { "
    "$p = Get-ItemProperty $k -ErrorAction SilentlyContinue; "
    "if ($p) { foreach ($e in $p.PSObject.Properties) { "
    "if ($e.Name -notlike 'PS*') { $items += $e.Name } } } }; "
    "$folder = @(); "
    "foreach ($f in [Environment]::GetFolderPath('Startup'), "
    "[Environment]::GetFolderPath('CommonStartup')) { "
    "if ($f -and (Test-Path $f)) { $folder += (Get-ChildItem $f -File "
    "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) } }; "
    "@{ run_keys = @($items); startup_folder = @($folder) } | "
    "ConvertTo-Json -Compress -Depth 3"
)

#: Space that can be handed back, and whether Windows is already doing it.
#:
#: Only directories whose entire purpose is to hold discardable files. Nothing
#: here walks a user's documents, and Warden reports the number without ever
#: offering to delete anything it has not measured.
#:
#: Not recursive on the update cache. SoftwareDistribution\\Download can hold
#: tens of thousands of files, and walking it took longer than the bridge's
#: whole timeout for a number that only needs to be roughly right.
_RECLAIMABLE = (
    "$total = 0; $detail = @{}; "
    'foreach ($p in @($env:TEMP, "$env:WINDIR\\Temp")) { if (Test-Path $p) { '
    "$b = (Get-ChildItem $p -Recurse -File -Force -ErrorAction SilentlyContinue | "
    "Measure-Object -Property Length -Sum).Sum; "
    "if (-not $b) { $b = 0 }; $total += $b; $detail[$p] = [math]::Round($b/1MB) } }; "
    '$u = "$env:WINDIR\\SoftwareDistribution\\Download"; '
    "if (Test-Path $u) { "
    "$b = (Get-ChildItem $u -File -Force -ErrorAction SilentlyContinue | "
    "Measure-Object -Property Length -Sum).Sum; "
    "if (-not $b) { $b = 0 }; $total += $b; $detail[$u] = [math]::Round($b/1MB) }; "
    "$sense = (Get-ItemProperty "
    "'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy' "
    "-ErrorAction SilentlyContinue).'01'; "
    "@{ reclaimable_mb = [math]::Round($total/1MB); by_path = $detail; "
    "storage_sense_on = ($sense -eq 1) } | ConvertTo-Json -Compress -Depth 3"
)


class AuditSettingsCollector(Collector):
    id = "sys.audit"
    interval_s = 120.0
    description = "Configuration the audit examines: power management, servicing state, schedules."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_adapter_power(result)
        self._probe_defrag(result)
        self._probe_reboot(result)
        self._probe_drivers(result)
        self._probe_power_profile(result)
        self._probe_startup(result)
        self._probe_reclaimable(result)
        return result

    def _probe_drivers(self, result: ProbeResult) -> None:
        script = "Get-PnpDevice | Get-PnpDeviceProperty DEVPKEY_Device_DriverDate"
        try:
            rows, ms = self._ps.run_json(_DRIVER_DATES, timeout=30.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        drivers: list[JsonValue] = [
            {
                "name": row.get("DeviceName"),
                "provider": row.get("DriverProviderName"),
                "device_class": row.get("DeviceClass"),
                "driver_date": row.get("DriverDate"),
            }
            for row in as_rows(rows)
        ]
        result.observations.append(
            self.observation(
                "audit.drivers",
                ObservationKind.INVENTORY,
                drivers,
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

    def _probe_power_profile(self, result: ProbeResult) -> None:
        script = "powercfg /getactivescheme; powercfg /q SUB_PROCESSOR PROCTHROTTLEMAX"
        try:
            payload, ms = self._ps.run_json(_POWER_PROFILE)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        result.observations.append(
            self.observation(
                "audit.power.profile",
                ObservationKind.STATE,
                {
                    "scheme": data.get("scheme"),
                    "scheme_guid": data.get("scheme_guid"),
                    "ac_max_pct": data.get("ac_max_pct"),
                    "dc_max_pct": data.get("dc_max_pct"),
                    # Chassis 8, 9, 10, 14 and 30 are the portable types. Used
                    # only to decide whether a question applies, never to judge.
                    "is_portable": data.get("chassis") in (8, 9, 10, 11, 12, 14, 30, 31, 32),
                    "chassis": data.get("chassis"),
                },
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

    def _probe_startup(self, result: ProbeResult) -> None:
        script = "Get-ItemProperty ...CurrentVersion\\Run; Get-ChildItem <Startup>"
        try:
            payload, ms = self._ps.run_json(_STARTUP)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        run_keys = [str(x) for x in (data.get("run_keys") or [])]
        folder = [str(x) for x in (data.get("startup_folder") or [])]
        result.observations.append(
            self.observation(
                "audit.startup",
                ObservationKind.INVENTORY,
                {
                    "run_keys": list(run_keys),
                    "startup_folder": list(folder),
                    "count": len(run_keys) + len(folder),
                },
                probe=script,
                mechanism=Mechanism.REGISTRY,
                elapsed_ms=ms,
            )
        )

    def _probe_reclaimable(self, result: ProbeResult) -> None:
        script = "Measure-Object on %TEMP%, Windows\\Temp, SoftwareDistribution\\Download"
        try:
            payload, ms = self._ps.run_json(_RECLAIMABLE, timeout=30.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        result.observations.append(
            self.observation(
                "audit.storage.reclaimable",
                ObservationKind.METRIC,
                {
                    "reclaimable_mb": data.get("reclaimable_mb"),
                    "by_path": data.get("by_path"),
                    "storage_sense_on": bool(data.get("storage_sense_on")),
                },
                unit="MB",
                probe=script,
                mechanism=Mechanism.FILE,
                elapsed_ms=ms,
            )
        )

    def _probe_adapter_power(self, result: ProbeResult) -> None:
        script = "Get-NetAdapter | Get-NetAdapterPowerManagement"
        try:
            rows, ms = self._ps.run_json(_ADAPTER_POWER)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        adapters: list[dict[str, JsonValue]] = []
        for row in as_rows(rows):
            allow = row.get("AllowComputerToTurnOffDevice")
            adapters.append(
                {
                    "name": row.get("Name"),
                    # Tri-state on purpose. Some adapters do not expose the
                    # setting at all, and "the driver does not support this"
                    # must not be read as "power saving is off".
                    "power_saving": _tristate(allow),
                    "raw": allow,
                }
            )
        result.observations.append(
            self.observation(
                "audit.wifi.power_management",
                ObservationKind.STATE,
                list(adapters),
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )

    def _probe_defrag(self, result: ProbeResult) -> None:
        script = "Get-ScheduledTask -TaskName ScheduledDefrag"
        try:
            rows, ms = self._ps.run_json(_DEFRAG_TASK)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        task = next(iter(as_rows(rows)), None)
        result.observations.append(
            self.observation(
                "audit.defrag.schedule",
                ObservationKind.STATE,
                {
                    "present": task is not None,
                    "state": task.get("State") if task else None,
                },
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

    def _probe_reboot(self, result: ProbeResult) -> None:
        script = "Test-Path RebootPending; Test-Path RebootRequired; PendingFileRenameOperations"
        try:
            payload, ms = self._ps.run_json(_REBOOT_PENDING)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        result.observations.append(
            self.observation(
                "audit.servicing.reboot_pending",
                ObservationKind.STATE,
                {
                    "servicing": bool(data.get("servicing")),
                    "windows_update": bool(data.get("windows_update")),
                    "file_renames": bool(data.get("file_renames")),
                    "last_boot": data.get("last_boot"),
                },
                probe=script,
                mechanism=Mechanism.REGISTRY,
                elapsed_ms=ms,
            )
        )


def _tristate(value: JsonValue) -> bool | None:
    """PowerShell booleans arrive as 'True'/'False' strings through JSON.

    None means the adapter does not expose the setting, which is a different
    fact from it being disabled and must not be flattened into one.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    return None
