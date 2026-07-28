"""Camera and microphone faults, separated by cause rather than by symptom.

A user reports one thing -- "my camera is black" -- and there are three answers
with three different fixes. Reporting them as one symptom would force the
reasoner to guess; reporting them separately means the evidence decides.

Consent is deliberately three-valued. A missing registry key is not "Deny":
Windows treats an absent value as allowed, and inventing a denial because a key
does not exist would be a false alarm on a clean install.
"""

from __future__ import annotations

from warden.collectors.privacy import CAPABILITIES
from warden.contracts import Severity, Symptom
from warden.detectors.base import Detector
from warden.store import ObservationStore, as_dict, as_list

#: Configuration Manager code 22 means the device was deliberately disabled,
#: which is a different fault from one that has failed.
_DISABLED_CODE = 22

_SYMPTOM_BY_LABEL = {
    "camera": ("CAM.BLOCKED_BY_PRIVACY", "camera"),
    "microphone": ("MIC.BLOCKED_BY_PRIVACY", "microphone"),
}


class PrivacyBlockDetector(Detector):
    """Access switched off in Privacy settings, at either scope."""

    id = "sys.privacy"
    raises = ("CAM.BLOCKED_BY_PRIVACY", "MIC.BLOCKED_BY_PRIVACY")

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        symptoms: list[Symptom] = []
        for label in CAPABILITIES.values():
            observation = store.latest(f"privacy.{label}")
            if observation is None:
                continue
            consent = as_dict(observation.value)
            user, machine = consent.get("user"), consent.get("machine")
            # Machine scope wins, and is the one a user cannot see in their own
            # Settings app -- so it is worth calling out separately.
            blocked_machine = machine == "Deny"
            blocked_user = user == "Deny"
            if not blocked_machine and not blocked_user:
                continue

            code, noun = _SYMPTOM_BY_LABEL[label]
            symptoms.append(
                self.symptom(
                    code,
                    severity=Severity.CRITICAL,
                    title=f"Windows privacy settings are blocking the {noun}",
                    detail=(
                        "Access is set to Deny "
                        + (
                            "for the whole machine, which overrides your own setting."
                            if blocked_machine
                            else "for your user account."
                        )
                    ),
                    facts={
                        "capability": consent.get("capability"),
                        "device": noun,
                        "user_consent": user,
                        "machine_consent": machine,
                        # Which scope to change. Machine scope needs elevation
                        # and reverses an administrator's decision, so the two
                        # are not interchangeable.
                        "blocked_scope": "machine" if blocked_machine else "user",
                        "denied_app_count": len(as_list(consent.get("denied_apps"))),
                    },
                    evidence=[observation],
                )
            )
        return symptoms


class CameraDeviceDetector(Detector):
    """The camera hardware itself, as Windows sees it."""

    id = "cam.device"
    raises = ("CAM.DEVICE_DISABLED",)

    def evaluate(self, store: ObservationStore) -> list[Symptom]:
        observation = store.latest("cam.devices")
        if observation is None:
            return []
        cameras = [as_dict(raw) for raw in as_list(observation.value)]
        if not cameras:
            return []  # No camera fitted. Not a fault; many desktops have none.

        disabled = [
            camera
            for camera in cameras
            if camera.get("problem_code") == _DISABLED_CODE
            or str(camera.get("status")).lower() in {"error", "degraded", "unknown"}
        ]
        if not disabled:
            return []

        worst = disabled[0]
        turned_off = worst.get("problem_code") == _DISABLED_CODE
        return [
            self.symptom(
                "CAM.DEVICE_DISABLED",
                severity=Severity.CRITICAL,
                title=(
                    f"{worst.get('name')} is switched off in Device Manager"
                    if turned_off
                    else f"{worst.get('name')} is not working"
                ),
                detail=(
                    f"Windows reports the device as {worst.get('status')!r}"
                    + (
                        " with problem code 22, which means it was disabled deliberately."
                        if turned_off
                        else "."
                    )
                ),
                facts={
                    "name": worst.get("name"),
                    "instance_id": worst.get("instance_id"),
                    "status": worst.get("status"),
                    "problem_code": worst.get("problem_code"),
                    "deliberately_disabled": turned_off,
                    "camera_count": len(cameras),
                },
                evidence=[observation],
            )
        ]
