"""Device health and the system event log -- the two slow, high-value probes.

Both are expensive relative to a counter read (device enumeration walks the PnP
tree; ``Get-WinEvent`` opens and filters an ETW channel), so both declare a long
interval and are skipped on most ticks. The orchestrator also re-runs them on
demand when an incident opens, because the thirty seconds before a fault is
exactly when the event log becomes interesting.
"""

from __future__ import annotations

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

#: Windows Configuration Manager problem codes, restricted to the ones that
#: actually distinguish causes for a user. The full table has ~50 entries, most
#: of which say "something is wrong" less precisely than code 10 does.
CM_PROBLEM_CODES: dict[int, str] = {
    1: "not configured correctly",
    3: "driver may be corrupted, or the system is low on memory",
    10: "cannot start",
    12: "cannot find enough free resources to use",
    14: "needs a restart to work properly",
    18: "drivers need to be reinstalled",
    19: "registry configuration is incomplete or damaged",
    21: "Windows is removing the device",
    22: "disabled",
    24: "not present, not working properly, or missing a driver",
    28: "drivers are not installed",
    31: "Windows cannot load the drivers required for this device",
    32: "start type for this driver is disabled",
    37: "driver returned a failure on initialisation",
    39: "driver is corrupted or missing",
    43: "stopped because it reported problems",
    45: "not currently connected",
    52: "driver may be unsigned or its signature could not be verified",
}

_PROBLEM_DEVICES = json_pipeline(
    "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
    "Where-Object { $_.ConfigManagerErrorCode -ne 0 -and $_.ConfigManagerErrorCode -ne $null } | "
    "Select-Object Name,DeviceID,ConfigManagerErrorCode,Status,Service,PNPClass",
    depth=2,
)

#: Critical and Error level entries only. Warnings in the System log are
#: constant background noise on a healthy machine and would drown the signal.
_SYSTEM_ERRORS = json_pipeline(
    "Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2;"
    "StartTime=(Get-Date).AddMinutes(-30)} -MaxEvents 40 -ErrorAction SilentlyContinue | "
    "Select-Object Id,ProviderName,LevelDisplayName,"
    "@{Name='Time';Expression={$_.TimeCreated.ToString('o')}},"
    "@{Name='Message';Expression={if($_.Message){"
    "($_.Message -split [char]10)[0].Trim().Substring(0,"
    "[Math]::Min(220,($_.Message -split [char]10)[0].Trim().Length))}else{''}}}",
    depth=2,
)


class DeviceCollector(Collector):
    id = "sys.devices"
    interval_s = 20.0
    description = "Devices Windows itself has flagged as faulted, with their problem codes."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        script = "Get-CimInstance Win32_PnPEntity | Where ConfigManagerErrorCode -ne 0"
        try:
            rows, ms = self._ps.run_json(_PROBLEM_DEVICES, timeout=20.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return result

        devices: list[dict[str, JsonValue]] = []
        for row in as_rows(rows):
            code = row.get("ConfigManagerErrorCode")
            code_int = code if isinstance(code, int) else -1
            devices.append(
                {
                    "name": row.get("Name"),
                    "device_id": row.get("DeviceID"),
                    "problem_code": code_int,
                    "problem": CM_PROBLEM_CODES.get(code_int, "reported an unspecified problem"),
                    "class": row.get("PNPClass"),
                    "service": row.get("Service"),
                    "status": row.get("Status"),
                }
            )
        result.observations.append(
            self.observation(
                "dev.problem_devices",
                ObservationKind.INVENTORY,
                list(devices),
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )
        return result


class EventLogCollector(Collector):
    id = "sys.eventlog"
    interval_s = 30.0
    description = "Critical and error entries from the Windows System log, last 30 minutes."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        script = "Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2}"
        try:
            rows, ms = self._ps.run_json(_SYSTEM_ERRORS, timeout=25.0)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return result

        entries = [
            {
                "id": row.get("Id"),
                "provider": row.get("ProviderName"),
                "level": row.get("LevelDisplayName"),
                "time": row.get("Time"),
                "message": row.get("Message"),
            }
            for row in as_rows(rows)
        ]
        result.observations.append(
            self.observation(
                "log.system_errors",
                ObservationKind.LOG_EVENT,
                list(entries),
                probe=script,
                mechanism=Mechanism.EVENTLOG,
                elapsed_ms=ms,
            )
        )
        return result
