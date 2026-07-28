"""Camera and microphone: the device, and the permission nobody thinks to check.

"My camera doesn't work" has three completely different causes that look
identical to the person reporting it:

1. the Frame Server service is stopped (covered by ``collectors/services.py``),
2. the device is disabled or faulted in Device Manager,
3. **camera access is switched off in Privacy settings.**

The third is the interesting one. It lives in a registry consent store, produces
a black image with no error message, and survives every reinstall and driver
update a frustrated user will try. Windows' own camera troubleshooter does not
look at it. It is the single best example of what this product is for: a cause
that is invisible from the symptom, and a fix that is one setting away once you
know where to look.

The same consent store governs the microphone, which is why both live here. "No
one can hear me on the call" has the same shape and the same fix.
"""

from __future__ import annotations

from pydantic import JsonValue

from warden.collectors.base import Collector, first
from warden.collectors.psbridge import (
    PowerShellBridge,
    PowerShellError,
    PowerShellUnavailable,
    as_rows,
    json_pipeline,
)
from warden.contracts import Mechanism, ObservationKind, ProbeResult

CONSENT_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"

#: The two capabilities Warden watches, keyed by the consent-store folder name.
CAPABILITIES = {
    "webcam": "camera",
    "microphone": "microphone",
}

_DEVICES = json_pipeline(
    "Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue | "
    "Select-Object FriendlyName,Status,InstanceId,ConfigManagerErrorCode"
)


def _consent_script(capability: str) -> str:
    """Read the global consent for a capability, plus any app denied individually.

    Both scopes matter and they are not equivalent: the machine-wide value under
    HKLM overrides the per-user one under HKCU, so a user who has "allowed" the
    camera can still be blocked by a setting they cannot see in their own
    Settings app.
    """
    user = f"HKCU:\\{CONSENT_ROOT}\\{capability}"
    machine = f"HKLM:\\{CONSENT_ROOT}\\{capability}"
    return (
        f"$u='{user}'; $m='{machine}'; "
        "$uv=(Get-ItemProperty $u -EA SilentlyContinue).Value; "
        "$mv=(Get-ItemProperty $m -EA SilentlyContinue).Value; "
        "$d=@(Get-ChildItem $u -EA SilentlyContinue | ForEach-Object "
        "{ if((Get-ItemProperty $_.PSPath -EA SilentlyContinue).Value -eq 'Deny')"
        "{ $_.PSChildName } }); "
        "[pscustomobject]@{User=$uv;Machine=$mv;DeniedApps=$d;AppCount="
        "@(Get-ChildItem $u -EA SilentlyContinue).Count} | ConvertTo-Json -Compress -Depth 3"
    )


class PrivacyCollector(Collector):
    id = "sys.privacy"
    interval_s = 30.0
    description = "Camera and microphone devices, and whether Windows privacy settings allow them."

    def __init__(self, bridge: PowerShellBridge) -> None:
        self._ps = bridge

    def probe(self) -> ProbeResult:
        result = ProbeResult()
        self._probe_devices(result)
        for capability, label in CAPABILITIES.items():
            self._probe_consent(result, capability, label)
        return result

    def _probe_devices(self, result: ProbeResult) -> None:
        script = "Get-PnpDevice -Class Camera"
        try:
            rows, ms = self._ps.run_json(_DEVICES)
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return
        cameras: list[dict[str, JsonValue]] = [
            {
                "name": row.get("FriendlyName"),
                "status": row.get("Status"),
                "instance_id": row.get("InstanceId"),
                "problem_code": row.get("ConfigManagerErrorCode"),
            }
            for row in as_rows(rows)
        ]
        result.observations.append(
            self.observation(
                "cam.devices",
                ObservationKind.INVENTORY,
                list(cameras),
                probe=script,
                mechanism=Mechanism.CIM,
                elapsed_ms=ms,
            )
        )

    def _probe_consent(self, result: ProbeResult, capability: str, label: str) -> None:
        script = f"Get-ItemProperty HKCU:\\{CONSENT_ROOT}\\{capability}"
        try:
            payload, ms = self._ps.run_json(_consent_script(capability))
        except (PowerShellError, PowerShellUnavailable) as exc:
            result.errors.append(self.failure(script, exc))
            return

        row = first(as_rows(payload))
        denied = row.get("DeniedApps")
        result.observations.append(
            self.observation(
                f"privacy.{label}",
                ObservationKind.STATE,
                {
                    "capability": capability,
                    # Absent means the key does not exist, which Windows treats
                    # as allowed. Recording None rather than guessing "Allow"
                    # keeps the distinction visible to the detector.
                    "user": row.get("User"),
                    "machine": row.get("Machine"),
                    "denied_apps": denied if isinstance(denied, list) else [],
                    "app_count": row.get("AppCount"),
                },
                probe=script,
                mechanism=Mechanism.REGISTRY,
                elapsed_ms=ms,
            )
        )
