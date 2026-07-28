"""Restarting a Windows service, bound to an allowlist.

One playbook covers six subsystems. The safety here rests on two independent
limits rather than one: the parameter pattern rejects anything that is not a
plain service name, and the guard then checks that name against the table of
services Warden actually watches. A reasoner cannot restart the security
subsystem, a database, or anything else it happens to know the name of -- the
reachable set is exactly the six rows in ``collectors/services.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from warden.collectors.services import BY_NAME, RESTARTABLE
from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import Playbook
from warden.store import ObservationStore, as_dict, as_list


class ServiceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Windows service names are alphanumerics and a couple of punctuation marks.
    #: The pattern is the first of two gates; the guard below is the real one.
    service: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


def _is_watched_and_stopped(params: BaseModel, store: ObservationStore) -> str | None:
    """Only restart a service Warden watches and has observed to be stopped."""
    assert isinstance(params, ServiceParams)
    if params.service not in RESTARTABLE:
        return (
            f"{params.service!r} is not one of the services Warden watches "
            f"({', '.join(sorted(RESTARTABLE))})"
        )
    observation = store.latest("sys.services")
    if observation is None:
        return "no service reading is available to confirm the current state"
    for raw in as_list(observation.value):
        row = as_dict(raw)
        if row.get("name") == params.service:
            if not row.get("present"):
                return f"{params.service!r} is not installed on this machine"
            if row.get("status") == 4:
                return f"{params.service!r} is already running"
            return None
    return f"{params.service!r} was not in the last service reading"


def _bind_service(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {"service": symptom.facts.get("service")}


SERVICE_RESTART = Playbook(
    id="sys.service.restart",
    title="Restart the Windows service behind this",
    summary=(
        "Starts the stopped Windows service that the affected feature depends on, "
        "along with anything it in turn depends on."
    ),
    when_to_use=(
        "A service that is configured to start automatically has stopped, and the "
        "feature it provides -- printing, audio, Bluetooth, update, search or camera "
        "-- is unavailable as a result."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=ServiceParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # -ErrorAction Stop so a refusal becomes a non-zero exit rather than a
        # warning the executor would read as success.
        "Start-Service -Name '{service}' -ErrorAction Stop",
    ],
    expected_effect=(
        "The service starts and the feature becomes available again, usually within "
        "a couple of seconds. Nothing else on the machine is affected."
    ),
    verify=VerifySpec(
        probes=["sys.services"],
        predicate=PredicateRef(
            id="service.running",
            describe="Re-read the service list and confirm it is now running.",
        ),
        timeout_s=25.0,
        settle_s=2.0,
    ),
    est_duration_s=6.0,
    requires_admin=True,
    guard=_is_watched_and_stopped,
    binder=_bind_service,
    note="Starts one named service. No service is installed, removed or reconfigured.",
    tags=("services",),
)


class EnableServiceParams(ServiceParams):
    """Same shape; separate model so the two actions cannot be confused."""


ENABLE_AND_START = Playbook(
    id="sys.service.enable",
    title="Re-enable the service and start it",
    summary=("Changes a disabled Windows service back to starting automatically, then starts it."),
    when_to_use=(
        "The service is Disabled rather than merely stopped. Starting it alone would "
        "fail, and even if it succeeded it would not start again after a restart."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=EnableServiceParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Set-Service -Name '{service}' -StartupType Automatic -ErrorAction Stop; "
        "Start-Service -Name '{service}' -ErrorAction Stop",
    ],
    expected_effect=(
        "The service is set to start with Windows and is started now. If it was "
        "disabled deliberately -- by an administrator, or by software you installed "
        "-- this reverses that decision."
    ),
    verify=VerifySpec(
        probes=["sys.services"],
        predicate=PredicateRef(
            id="service.running",
            describe="Confirm the service is running and no longer disabled.",
        ),
        timeout_s=30.0,
        settle_s=2.0,
    ),
    est_duration_s=8.0,
    requires_admin=True,
    guard=_is_watched_and_stopped,
    binder=_bind_service,
    note=(
        "Changes a startup setting as well as starting the service, which is why "
        "this is treated as more intrusive than a plain restart."
    ),
    tags=("services",),
)

SERVICE_PLAYBOOKS = [SERVICE_RESTART, ENABLE_AND_START]

#: Symptom code -> the two actions, gentlest first. Built from the same table the
#: collector uses, so a new watched service is covered without touching this map.
SERVICE_CANDIDATES = {
    service.symptom_code: ("sys.service.restart", "sys.service.enable")
    for service in BY_NAME.values()
}
