"""Shared primitives for every contract in Warden.

Everything that crosses a module boundary is defined under ``warden.contracts``.
Modules import contracts; contracts import nothing from the rest of the package.
That one rule is what lets the collector, detector, reasoner, executor and UI
layers be understood -- and changed -- independently.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Timezone-aware now. Naive datetimes are a bug; the UI sorts on these."""
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Contract(BaseModel):
    """Base for every wire type.

    ``extra="forbid"`` is deliberate: an LLM response or a hand-edited fixture
    that carries a field we don't know about is a contract violation we want to
    hear about loudly, not silently drop.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class Mechanism(StrEnum):
    """How an observation was physically obtained. Shown to the user verbatim."""

    CIM = "cim"  # Get-CimInstance / WMI
    PDH = "pdh"  # performance counters
    EVENTLOG = "eventlog"
    NETSH = "netsh"
    NETCMDLET = "netcmdlet"  # Get-NetAdapter and friends (locale-independent)
    PSUTIL = "psutil"
    SOCKET = "socket"
    DOTNET = "dotnet"  # LibreHardwareMonitor via pythonnet
    REGISTRY = "registry"
    REPLAY = "replay"  # sourced from a recorded session, never from live hardware


class Domain(StrEnum):
    """Which layer of the machine a hypothesis blames.

    ``HARDWARE`` is the one that matters: it is the only value that routes to
    servicing instead of to a command.
    """

    SOFTWARE = "software"
    CONFIGURATION = "configuration"
    DRIVER = "driver"
    HARDWARE = "hardware"
    ENVIRONMENT = "environment"


class Verdict(StrEnum):
    """The agent's decision about what kind of answer this problem has."""

    ACTIONABLE = "actionable"  # we have a fix and want approval to run it
    NEEDS_SERVICE = "needs_service"  # physical cause; no command can fix this
    NEEDS_MORE_DATA = "needs_more_data"  # evidence is too thin to act on
    NO_ISSUE = "no_issue"  # symptom cleared or was benign


class RiskTier(StrEnum):
    """How much damage an action could do if we are wrong about the diagnosis."""

    READ_ONLY = "read_only"  # gathers more data, changes nothing
    REVERSIBLE = "reversible"  # changes state, trivially undone (reconnect, flush dns)
    INTRUSIVE = "intrusive"  # restarts a device or service; user-visible disruption


class Source(StrEnum):
    """Where the observation stream is coming from. Surfaced in the UI header.

    Replay exists so the UI and the test-suite can run without hardware, and so
    a recorded incident can be re-examined after the fact. It is always labelled.
    A build can never silently present replayed data as live.
    """

    LIVE = "live"
    REPLAY = "replay"


class Ref(Contract):
    """A pointer from a conclusion back to the evidence that produced it."""

    observation_id: str
    note: str | None = Field(
        default=None, description="Why this observation matters to the claim citing it."
    )
