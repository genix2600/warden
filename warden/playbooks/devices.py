"""Device and storage playbooks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import NoParams, Playbook
from warden.store import ObservationStore


class DeviceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(min_length=4, max_length=200)
    device_name: str = Field(min_length=1, max_length=120)


def _device_is_faulted(params: BaseModel, store: ObservationStore) -> str | None:
    """Only restart a device Windows currently reports as faulted.

    Without this, a plausible-sounding instance path would be enough to cycle an
    arbitrary device -- including the storage controller the machine is booted
    from. The guard reduces the reachable set to devices already carrying a
    problem code, which is a far smaller and far safer surface.
    """
    assert isinstance(params, DeviceParams)
    devices = store.value("dev.problem_devices")
    if not isinstance(devices, list) or not devices:
        return "no device on this machine is currently reporting a fault"
    faulted = {d.get("device_id") for d in devices if isinstance(d, dict)}
    if params.device_id not in faulted:
        return f"{params.device_name!r} is not among the devices currently reporting a fault"
    return None


def _bind_device(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {
        "device_id": symptom.facts.get("first_recoverable_device_id"),
        "device_name": symptom.facts.get("first_recoverable_name"),
    }


DRIVER_RESTART = Playbook(
    id="dev.driver.restart",
    title="Restart the faulted device",
    summary="Stops and restarts a device that Windows has flagged with a problem code.",
    when_to_use=(
        "A device reports a recoverable Configuration Manager problem code -- typically "
        "10, 43 or 31 -- which often clears with a device restart and no reboot."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=DeviceParams,
    argv_template=["pnputil", "/restart-device", "{device_id}"],
    expected_effect=(
        "The device disappears and re-enumerates. If it is a display or input device, "
        "expect a brief flicker or pause."
    ),
    verify=VerifySpec(
        probes=["sys.devices"],
        predicate=PredicateRef(
            id="device.healthy",
            describe="Re-enumerate devices and check the problem code has cleared.",
        ),
        timeout_s=40.0,
        settle_s=5.0,
    ),
    est_duration_s=12.0,
    requires_admin=True,
    reversible=True,
    guard=_device_is_faulted,
    binder=_bind_device,
    note="Restarts one device only; drivers are not uninstalled or modified.",
    tags=("devices", "drivers"),
)

TEMP_REPORT = Playbook(
    id="sys.disk.temp_report",
    title="Measure reclaimable temporary files",
    summary="Reports how much space the user and system temporary folders are holding.",
    when_to_use="A drive is nearly full and the user needs to know what is safe to remove.",
    risk=RiskTier.READ_ONLY,
    params_model=NoParams,
    # Deliberately a measurement and not a deletion. Warden's registry contains
    # no action that destroys user data: the difference between "here is 14 GB of
    # temporary files and where they are" and quietly deleting them is the whole
    # distance between this and the "PC optimiser" software it is competing with.
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        'foreach ($p in @($env:TEMP, "$env:SystemRoot\\Temp")) { '
        "$b = (Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue | "
        "Measure-Object Length -Sum).Sum; "
        "'{0}: {1:N1} GB' -f $p, ($b / 1GB) }",
    ],
    expected_effect="Prints the size of each temporary folder. Nothing is deleted.",
    verify=VerifySpec(
        probes=[],
        predicate=PredicateRef(
            id="report.only", describe="No state changes, so there is nothing to re-check."
        ),
        timeout_s=10.0,
    ),
    est_duration_s=20.0,
    tags=("storage", "diagnostic"),
)

DEVICE_PLAYBOOKS = [DRIVER_RESTART, TEMP_REPORT]
