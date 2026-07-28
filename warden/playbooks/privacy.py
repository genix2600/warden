"""Turning camera and microphone access back on, and re-enabling the device.

The registry is the one place where a careless action could do real damage, so
this module never accepts a path. The parameters are two closed enumerations --
which capability, and which scope -- and the key is assembled here in source from
those two values. There is no string a reasoner could supply that reaches a
different key, which is a stronger guarantee than validating a path would be.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field

from warden.collectors.privacy import CONSENT_ROOT
from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import Playbook
from warden.store import ObservationStore, as_dict

Capability = Literal["webcam", "microphone"]
Scope = Literal["user", "machine"]

_HIVE = {"user": "HKCU:", "machine": "HKLM:"}


def consent_key(capability: Capability, scope: Scope) -> str:
    """The only way a registry path is produced in this codebase."""
    return f"{_HIVE[scope]}\\{CONSENT_ROOT}\\{capability}"


class PrivacyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: Capability
    scope: Scope = "user"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scope_hive(self) -> str:
        """The registry hive, derived rather than supplied.

        The argv template needs "HKCU:" or "HKLM:", but accepting that as a
        parameter would mean accepting a string that points at a hive. Deriving
        it from the validated ``scope`` enum means the only two values that can
        ever reach the command are these two.
        """
        return _HIVE[self.scope]


def _is_actually_denied(params: BaseModel, store: ObservationStore) -> str | None:
    """Only flip a consent value Warden has observed to be Deny."""
    assert isinstance(params, PrivacyParams)
    label = "camera" if params.capability == "webcam" else "microphone"
    observation = store.latest(f"privacy.{label}")
    if observation is None:
        return f"no privacy reading for the {label} is available"
    consent = as_dict(observation.value)
    if consent.get(params.scope) != "Deny":
        return (
            f"{label} access is not set to Deny at {params.scope} scope, so there is "
            f"nothing to change"
        )
    return None


def _bind_privacy(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {
        "capability": symptom.facts.get("capability"),
        "scope": symptom.facts.get("blocked_scope"),
    }


PRIVACY_ALLOW = Playbook(
    id="privacy.allow",
    title="Turn the privacy setting back on",
    summary=(
        "Sets Windows' camera or microphone access back to Allow, which is the "
        "setting a black camera or a silent microphone usually comes down to."
    ),
    when_to_use=(
        "The device is present and its service is running, but Windows privacy "
        "settings are set to Deny -- so applications get a black image or silence "
        "with no error message explaining why."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=PrivacyParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # {capability} and {scope} are closed enumerations validated by Pydantic
        # before this renders, so neither can carry anything but one of four
        # known words.
        "Set-ItemProperty -Path "
        "'{scope_hive}\\" + CONSENT_ROOT + "\\{capability}' "
        "-Name Value -Value Allow -ErrorAction Stop",
    ],
    expected_effect=(
        "Applications can use the device again immediately. Anything already open "
        "may need to be restarted before it notices."
    ),
    verify=VerifySpec(
        probes=["sys.privacy"],
        predicate=PredicateRef(
            id="privacy.allowed",
            describe="Re-read the privacy setting and confirm it is no longer Deny.",
        ),
        timeout_s=15.0,
        settle_s=1.0,
    ),
    est_duration_s=3.0,
    # Machine scope needs elevation; user scope does not. Declared as the
    # stricter of the two so Warden refuses up front rather than failing
    # halfway, and the approval card is honest about what it needs.
    requires_admin=True,
    guard=_is_actually_denied,
    binder=_bind_privacy,
    note=(
        "Changes exactly one registry value, the same one the Settings app writes. "
        "You can undo it in Settings > Privacy & security at any time."
    ),
    tags=("privacy", "camera", "microphone"),
)


class DeviceEnableParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(min_length=4, max_length=200)
    device_name: str = Field(min_length=1, max_length=120)


def _device_is_disabled(params: BaseModel, store: ObservationStore) -> str | None:
    assert isinstance(params, DeviceEnableParams)
    observation = store.latest("cam.devices")
    if observation is None or not isinstance(observation.value, list):
        return "no camera inventory is available"
    for raw in observation.value:
        device = as_dict(raw)
        if device.get("instance_id") == params.instance_id:
            if device.get("problem_code") != 22 and str(device.get("status")) == "OK":
                return f"{params.device_name!r} is not disabled"
            return None
    return f"{params.device_name!r} is not among the cameras Warden can see"


def _bind_device(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {
        "instance_id": symptom.facts.get("instance_id"),
        "device_name": symptom.facts.get("name"),
    }


CAMERA_ENABLE = Playbook(
    id="cam.device.enable",
    title="Re-enable the camera in Device Manager",
    summary="Switches a camera that was disabled in Device Manager back on.",
    when_to_use=(
        "The camera is present but reports problem code 22, meaning somebody or "
        "something disabled it deliberately."
    ),
    risk=RiskTier.INTRUSIVE,
    params_model=DeviceEnableParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false -ErrorAction Stop",
    ],
    expected_effect="The camera re-enumerates and becomes available to applications.",
    verify=VerifySpec(
        probes=["sys.privacy"],
        predicate=PredicateRef(
            id="camera.enabled",
            describe="Re-enumerate cameras and confirm none is still disabled.",
        ),
        timeout_s=30.0,
        settle_s=4.0,
    ),
    est_duration_s=10.0,
    requires_admin=True,
    guard=_device_is_disabled,
    binder=_bind_device,
    tags=("camera", "devices"),
)

PRIVACY_PLAYBOOKS = [PRIVACY_ALLOW, CAMERA_ENABLE]
