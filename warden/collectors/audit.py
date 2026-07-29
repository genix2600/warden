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
        return result

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
