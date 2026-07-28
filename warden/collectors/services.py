"""Windows services, and the subsystems that live or die with them.

Six domains a user would describe completely differently -- "no sound", "the
printer is stuck", "Bluetooth vanished", "Windows Update does nothing", "search
returns nothing", "my camera is black" -- reduce to the same question: is the
service behind it running, and is it set to start on its own.

That shared shape is worth exploiting rather than writing six near-identical
collectors. One collector reads a table of services, one detector maps a stopped
service to the symptom a user would recognise, and one playbook restarts it.
Adding a seventh subsystem is a row in ``WATCHED``, not a module.

The table is also a deliberate allowlist. ``sys.service.restart`` will only touch
a service named here, so the reasoner cannot be talked into restarting the
security subsystem or a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import JsonValue

from warden.collectors.base import Collector, num
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult


@dataclass(frozen=True, slots=True)
class WatchedService:
    """One Windows service, and what a user notices when it stops."""

    name: str
    #: What the user would call the thing that broke, not what Microsoft calls it.
    subsystem: str
    symptom_code: str
    #: Written for someone who does not know what a "service" is.
    consequence: str


WATCHED: tuple[WatchedService, ...] = (
    WatchedService(
        name="Spooler",
        subsystem="printing",
        symptom_code="PRINT.SPOOLER_STOPPED",
        consequence="nothing can print, and print jobs silently queue up or vanish",
    ),
    WatchedService(
        name="Audiosrv",
        subsystem="audio",
        symptom_code="AUDIO.SERVICE_STOPPED",
        consequence="there is no sound from any application, and volume controls do nothing",
    ),
    WatchedService(
        name="bthserv",
        subsystem="Bluetooth",
        symptom_code="BT.SERVICE_STOPPED",
        consequence="Bluetooth devices will not pair or reconnect, and may disappear entirely",
    ),
    WatchedService(
        name="wuauserv",
        subsystem="Windows Update",
        symptom_code="UPDATE.SERVICE_STOPPED",
        consequence="security updates stop arriving, silently and indefinitely",
    ),
    WatchedService(
        name="WSearch",
        subsystem="Windows Search",
        symptom_code="SEARCH.SERVICE_STOPPED",
        consequence="the Start menu and File Explorer return no results for files that exist",
    ),
    WatchedService(
        name="FrameServer",
        subsystem="camera",
        symptom_code="CAM.SERVICE_STOPPED",
        consequence="the camera shows a black image in every application",
    ),
)

#: The allowlist the restart playbook is bound to.
RESTARTABLE = frozenset(service.name for service in WATCHED)

BY_NAME = {service.name: service for service in WATCHED}

_SERVICES = json_pipeline(
    "Get-Service -Name "
    + ",".join(f"'{s.name}'" for s in WATCHED)
    + " -ErrorAction SilentlyContinue | "
    "Select-Object Name,Status,StartType,DisplayName"
)


class ServiceCollector(Collector):
    id = "sys.services"
    interval_s = 15.0
    description = (
        "The Windows services behind printing, audio, Bluetooth, update, search and camera."
    )

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        script = "Get-Service -Name " + ",".join(s.name for s in WATCHED)
        try:
            rows, ms = self._ps.run_json(_SERVICES)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return result

        found = {str(row.get("Name")): row for row in as_rows(rows) if row.get("Name") is not None}
        services: list[dict[str, JsonValue]] = []
        for watched in WATCHED:
            row = found.get(watched.name)
            services.append(
                {
                    "name": watched.name,
                    "subsystem": watched.subsystem,
                    # Absent is distinct from stopped: a machine with no
                    # Bluetooth hardware genuinely has no bthserv, and calling
                    # that a fault would be a false alarm on every desktop.
                    "present": row is not None,
                    "status": row.get("Status") if row else None,
                    "start_type": row.get("StartType") if row else None,
                    "display_name": row.get("DisplayName") if row else None,
                }
            )
        result.observations.append(
            self.observation(
                "sys.services",
                ObservationKind.STATE,
                list(services),
                probe=script,
                mechanism=Mechanism.NETCMDLET,
                elapsed_ms=ms,
            )
        )
        return result


#: PowerShell's ServiceControllerStatus enum. ConvertTo-Json serialises it as an
#: integer, and 4 is the only value that means "working".
SERVICE_STATUS = {
    1: "stopped",
    2: "start pending",
    3: "stop pending",
    4: "running",
    5: "continue pending",
    6: "pause pending",
    7: "paused",
}

#: Win32_Service StartMode as an integer. 4 is Disabled -- a service that is
#: disabled will not survive a restart, so the advice has to differ.
START_TYPE = {2: "automatic", 3: "manual", 4: "disabled"}


def status_name(value: JsonValue) -> str:
    code = num(value)
    return SERVICE_STATUS.get(int(code), str(value)) if code is not None else str(value)


def start_type_name(value: JsonValue) -> str:
    code = num(value)
    return START_TYPE.get(int(code), str(value)) if code is not None else str(value)
