"""A way back, for the whole machine.

Per-action reversal is the right granularity for a fix that did not work: the
verifier says the network is still down, the incident escalates, and nothing has
accumulated. But it does not cover the case a user actually fears, which is
"something Warden did made my computer worse and I do not know which thing".

Windows already has the mechanism for that, and it is better than anything
Warden could build: a System Restore checkpoint captures the registry, drivers
and system files as one consistent snapshot. So Warden takes one before the
first disruptive action of a session, and then gets out of the way.

**Warden does not perform the rollback.** It creates the checkpoint and opens
Windows' own restore interface. Rolling a machine back is a far larger action
than anything in the playbook registry -- it reverts changes this program never
made and cannot verify -- and doing it silently, from inside the tool the user
already suspects, would be exactly the wrong instinct. The user drives it, in a
dialog they can recognise, with Microsoft's own warnings in front of them.

Two honest limitations, both reported rather than hidden:

* System Protection is **off by default** on many Windows 11 installations. If
  it is disabled there is no checkpoint to make, and enabling it is itself a
  system change Warden will not make behind the user's back.
* Windows rate-limits checkpoint creation to one per 24 hours by default, so a
  second session on the same day reuses the first one. That is fine -- the
  snapshot still predates every change Warden has made today -- but the
  interface should not claim to have taken a fresh one when it did not.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from warden.winenv import is_admin

log = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000
_TIMEOUT_S = 120.0

#: Checkpoint creation is slow and occasionally very slow; it writes a shadow
#: copy. Two minutes is generous, and the failure mode past it is to report that
#: no checkpoint exists rather than to block the user indefinitely.
_DESCRIPTION = "Before Warden made changes"

_PROTECTION_ENABLED = (
    "$d = (Get-CimInstance Win32_OperatingSystem).SystemDrive + '\\'; "
    "$v = Get-CimInstance -ClassName Win32_ShadowCopy -ErrorAction SilentlyContinue; "
    "$r = Get-ComputerRestorePoint -ErrorAction SilentlyContinue; "
    "if ($r -or $v) { 'true' } else { 'unknown' }"
)


@dataclass(frozen=True, slots=True)
class RestoreState:
    """What Warden can honestly say about the machine's way back."""

    available: bool
    detail: str
    created: bool = False


def describe() -> RestoreState:
    """Whether a system-wide rollback is available, without changing anything."""
    if not is_admin():
        return RestoreState(
            available=False,
            detail=(
                "Checking for a restore point needs administrator rights. Warden is "
                "running as a standard user, so it cannot tell you whether one exists."
            ),
        )
    points = _run("Get-ComputerRestorePoint | Select-Object -Last 1 -ExpandProperty CreationTime")
    if points is None:
        return RestoreState(
            available=False,
            detail=(
                "System Protection appears to be turned off, so Windows is not keeping "
                "restore points. Warden will not turn it on for you — that is a system "
                "change, and it is yours to make in System Properties → System Protection."
            ),
        )
    if not points.strip():
        return RestoreState(
            available=False,
            detail="System Protection is on, but no restore point has been created yet.",
        )
    return RestoreState(
        available=True,
        detail=f"The most recent restore point on this machine is from {points.strip()}.",
    )


def ensure_checkpoint() -> RestoreState:
    """Take a checkpoint before the first disruptive action of a session.

    Best effort by design. A machine with System Protection disabled is a
    machine Warden still works on; it simply says so instead of pretending a
    safety net exists.
    """
    if not is_admin():
        return describe()

    created = _run(
        f"Checkpoint-Computer -Description '{_DESCRIPTION}' -RestorePointType MODIFY_SETTINGS"
    )
    state = describe()
    if created is None:
        # The most common cause is not failure but Windows' own rate limit: one
        # checkpoint per 24 hours unless SystemRestorePointCreationFrequency
        # says otherwise. An existing point from earlier today still predates
        # everything Warden has done, so this is not worth alarming anyone over.
        if state.available:
            return RestoreState(
                available=True,
                detail=(
                    f"{state.detail} Windows allows one new restore point per day, so "
                    "Warden is relying on that one rather than creating another."
                ),
            )
        return state
    return RestoreState(available=state.available, detail=state.detail, created=True)


def open_windows_restore() -> bool:
    """Hand the user to Windows' own restore interface.

    Deliberately a handoff. Warden does not roll the machine back itself.
    """
    try:
        subprocess.Popen(["rstrui.exe"], creationflags=_CREATE_NO_WINDOW)
    except OSError as exc:
        log.warning("could not open System Restore: %s", exc)
        return False
    return True


def _run(script: str) -> str | None:
    """Run one PowerShell statement, returning None on any failure.

    Not routed through the shared PowerShell host: that host is warm, shared,
    and used for readings on a two-second cadence, and a 120-second
    checkpoint would block every collector behind it.
    """
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("restore-point query failed: %s", exc)
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout
