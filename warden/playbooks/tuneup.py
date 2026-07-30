"""Actions the settings audit can offer, and the two it deliberately cannot.

These go through the same executor, the same four gates and the same approval
card as every other action in Warden. Nothing here is a second execution path.

What is different is the bar. A fix applies to a machine that is broken; these
apply to a machine that currently works, which is a higher bar and the reason
every one of them has to be undoable. The audit contract enforces that: a
recommendation whose action is not reversible cannot be constructed without a
record of the prior value, captured before the command runs.

Two obvious candidates are missing as a result.

**Deleting temporary files.** The classic cleanup action, and it cannot be
undone. Warden reports the gigabyte it measured and then recommends turning on
Storage Sense instead, which is revertible and fixes the problem permanently
rather than once. Being unable to offer the obvious action is the rule working.

**Disabling startup programs.** Reversible, but Warden does not know which of
them the user wants, so there is nothing for it to recommend. The check reports
the count and stops.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field

from warden.contracts import PredicateRef, RiskTier, Symptom, VerifySpec
from warden.playbooks.base import Playbook
from warden.store import ObservationStore, as_dict, as_float

#: Where Windows keeps the Storage Sense master switch. Assembled here rather
#: than accepted as a parameter, for the same reason the privacy playbook
#: assembles its key: there is no string a caller could supply that reaches a
#: different value.
STORAGE_SENSE_KEY = (
    "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\StorageSense\\Parameters\\StoragePolicy"
)


class StorageSenseParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: 1 turns it on, 0 turns it back off. Constrained to those two so the revert
    #: action can reuse this model without widening what may be written.
    enabled: int = Field(ge=0, le=1)


class ProcessorCeilingParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The ceiling to set, as a percentage. Bounded because powercfg will accept
    #: nonsense and quietly apply it.
    percent: int = Field(ge=1, le=100)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hex_value(self) -> str:
        """powercfg wants hex. Derived rather than supplied, so the only values
        that can reach the command are ones Pydantic has already bounded."""
        return f"0x{self.percent:08x}"


def _storage_sense_is_off(params: BaseModel, store: ObservationStore) -> str | None:
    """Only turn it on when Warden has read it as off, and vice versa."""
    assert isinstance(params, StorageSenseParams)
    observation = store.latest("audit.storage.reclaimable")
    if observation is None:
        return "no storage reading is available"
    currently_on = bool(as_dict(observation.value).get("storage_sense_on"))
    if params.enabled == 1 and currently_on:
        return "Storage Sense is already on, so there is nothing to change"
    if params.enabled == 0 and not currently_on:
        return "Storage Sense is already off, so there is nothing to change"
    return None


def _processor_is_capped(params: BaseModel, store: ObservationStore) -> str | None:
    """Refuse to 'restore' a ceiling that is already where it is being set."""
    assert isinstance(params, ProcessorCeilingParams)
    observation = store.latest("audit.power.profile")
    if observation is None:
        return "no power profile reading is available"
    ceiling = as_float(as_dict(observation.value).get("ac_max_pct"))
    if ceiling is None:
        return "Windows did not report a processor ceiling to compare against"
    if int(ceiling) == params.percent:
        return f"the ceiling is already {params.percent}%, so there is nothing to change"
    return None


def _bind_storage_sense(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {"enabled": 1}


def _bind_processor(symptom: Symptom, store: ObservationStore) -> dict[str, JsonValue]:
    return {"percent": 100}


STORAGE_SENSE = Playbook(
    id="tuneup.storage_sense",
    title="Let Windows clear temporary files on its own",
    summary=(
        "Turns on Storage Sense, so Windows removes temporary files and old "
        "update caches without anyone having to remember to do it."
    ),
    when_to_use=(
        "Temporary directories are holding more than a gigabyte and Storage Sense "
        "is switched off, so the space will keep accumulating until somebody "
        "clears it by hand."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=StorageSenseParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # {enabled} is bounded to 0 or 1 by Pydantic before this renders.
        "New-Item -Path '" + STORAGE_SENSE_KEY + "' -Force | Out-Null; "
        "Set-ItemProperty -Path '" + STORAGE_SENSE_KEY + "' "
        "-Name '01' -Value {enabled} -Type DWord -ErrorAction Stop",
    ],
    expected_effect=(
        "Windows starts clearing temporary files on a schedule. Nothing is deleted "
        "at the moment you approve this; the space comes back over the following "
        "days."
    ),
    verify=VerifySpec(
        probes=["sys.audit"],
        predicate=PredicateRef(
            id="tuneup.storage_sense_on",
            describe="Re-read the setting and confirm Windows now says it is on.",
        ),
        timeout_s=20.0,
        settle_s=1.0,
    ),
    est_duration_s=3.0,
    # A per-user setting under HKCU, so no elevation is needed.
    requires_admin=False,
    guard=_storage_sense_is_off,
    binder=_bind_storage_sense,
    # The same playbook, with enabled=0, is the way back. One command that can
    # write exactly two values is a smaller surface than two commands.
    rollback_action_id="tuneup.storage_sense",
)

PROCESSOR_CEILING = Playbook(
    id="tuneup.processor_ceiling",
    title="Let the processor run at full speed on mains power",
    summary=(
        "Raises the maximum processor state back to 100% on the active power "
        "plan, undoing a cap that leaves the machine running at a fraction of "
        "what it can do."
    ),
    when_to_use=(
        "The active plan limits the processor to less than 100% while plugged in. "
        "Nothing in Windows surfaces this, and it is usually left behind by a "
        "battery-saving tool or a manufacturer utility."
    ),
    risk=RiskTier.REVERSIBLE,
    params_model=ProcessorCeilingParams,
    argv_template=[
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        # {percent} is bounded to 1-100 by Pydantic before this renders.
        "powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR "
        "PROCTHROTTLEMAX {percent}; powercfg /setactive SCHEME_CURRENT",
    ],
    expected_effect=(
        "The processor is allowed its full speed while plugged in. The change "
        "applies immediately and does not need a restart."
    ),
    verify=VerifySpec(
        probes=["sys.audit"],
        predicate=PredicateRef(
            id="tuneup.processor_uncapped",
            describe="Re-read the power plan and confirm the ceiling is back at 100%.",
        ),
        timeout_s=25.0,
        settle_s=2.0,
    ),
    est_duration_s=6.0,
    requires_admin=True,
    guard=_processor_is_capped,
    binder=_bind_processor,
    rollback_action_id="tuneup.processor_ceiling",
)

TUNEUP_PLAYBOOKS = (STORAGE_SENSE, PROCESSOR_CEILING)
