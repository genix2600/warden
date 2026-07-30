"""Preferences the user can change, and where they are kept.

Distinct from :mod:`warden.config`, which holds the thresholds Warden judges a
machine by. Those are measured, justified in ``docs/calibration.md``, and
changing one changes what counts as a fault. These are choices with no right
answer -- a colour scheme, whether the agent may act unprompted -- and nothing
here affects a diagnosis.

Kept in ``%LOCALAPPDATA%\\Warden`` beside the recorded sessions rather than in
the application folder, so an upgrade does not reset them and an install to a
read-only location still works.

**No credential is ever stored here.** That used to be true because Warden had
no credential to store; now that a cloud model can be enabled with a key the
user supplies, it is true because the key lives in a separate file
(:mod:`warden.credentials`) that this model cannot reach and the settings API
never returns. Keeping them apart is what allows ``GET /api/settings`` to stay a
plain, fully-serialised dump of everything below.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from warden.paths import data_path

log = logging.getLogger(__name__)

Theme = Literal["dark", "light"]

SETTINGS_FILE = "settings.json"


class Settings(BaseModel):
    """Everything the user may change. Serialised as-is."""

    theme: Theme = Field(
        default="dark",
        description=(
            "Dark is the default because the interface was designed in it and its "
            "contrast was checked there."
        ),
    )

    autodiagnose: bool = Field(
        default=False,
        description=(
            "Whether a finding should open an incident on its own. Off by default: "
            "Warden watches everything, but being told about a printer you do not "
            "own is noise, so reasoning waits until you ask."
        ),
    )

    muted_symptoms: list[str] = Field(
        default_factory=list,
        description=(
            "Symptom codes the user has told Warden to stop proposing fixes for. "
            "Still detected, still shown on the Health page, never turned into a "
            "proposal again until unmuted."
        ),
    )


def load() -> Settings:
    """Read the settings, falling back to defaults on anything unreadable.

    A corrupt or hand-edited file must not stop Warden starting. The defaults
    are all safe, so the worst case of ignoring the file is that someone's
    colour scheme resets -- which is a better outcome than an application that
    will not open.
    """
    path = data_path(SETTINGS_FILE)
    if not path.exists():
        return Settings()
    try:
        # utf-8-sig: a BOM, which Notepad and PowerShell both write by
        # default on Windows, otherwise makes this file silently unparseable
        # and resets every preference to its default.
        return Settings.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        log.warning("could not read %s, using defaults: %s", path, exc)
        return Settings()


def save(settings: Settings) -> None:
    path = data_path(SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.model_dump(), indent=2), encoding="utf-8")
