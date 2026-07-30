"""The one secret Warden can hold, kept as far from everything else as possible.

Warden shipped with no credential of any kind, and said so loudly: the settings
file "has nowhere to put a credential", the repository "has nowhere for an API
key to be added". Those were true, and they were true because there was nothing
to store rather than because anything prevented it.

Enabling a cloud model changes that, and the honest response is not to quietly
widen :class:`warden.settings.Settings` until a key fits. A secret has different
handling requirements from a colour scheme and belongs in a different place:

* **Its own file.** ``credentials.json``, never ``settings.json``.
* **Outside the settings model.** ``GET /api/settings`` serialises that model
  verbatim, so a key stored there would be handed to the interface on every page
  load and written into every session recording that captured the response.
* **Never returned.** The API exposes :func:`hint` and a boolean, and there is no
  route that returns the key. Once it is in, the only things that can read it
  are this module and the HTTP client that sends it to the provider.
* **Ignored twice.** ``.gitignore`` names it explicitly, in addition to the
  existing rule that covers ``settings.json``. That rule only covers this file by
  accident of both landing in the repository root during a source checkout, and
  a secret should not depend on an accident.

The key is still plaintext on disk under the user's own profile. That is the same
protection Windows gives every other application's stored token, and pretending
otherwise by adding obfuscation would be worse than saying it plainly: this is a
key you supplied, it sits in your user folder, and deleting the file removes it.
"""

from __future__ import annotations

import json
import logging

from warden.paths import data_path

log = logging.getLogger(__name__)

CREDENTIALS_FILE = "credentials.json"

_GROQ = "groq_api_key"


def load_key() -> str | None:
    """The stored Groq key, or None. Unreadable is treated as absent."""
    path = data_path(CREDENTIALS_FILE)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read %s, treating as unset: %s", path, exc)
        return None
    key = payload.get(_GROQ) if isinstance(payload, dict) else None
    return key.strip() if isinstance(key, str) and key.strip() else None


def save_key(key: str) -> None:
    """Store a key. Whitespace is stripped, because pasted keys carry it."""
    path = data_path(CREDENTIALS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({_GROQ: key.strip()}, indent=2), encoding="utf-8")


def clear_key() -> None:
    """Forget the key. Removing the file entirely rather than blanking the
    field, so nothing is left behind to be recovered from."""
    path = data_path(CREDENTIALS_FILE)
    path.unlink(missing_ok=True)


def hint(key: str | None) -> str:
    """What the interface is allowed to show: the last four characters.

    Enough to answer "is this the key I think it is" and useless to anyone
    reading over a shoulder or watching a screen recording of the demo.
    """
    if not key:
        return ""
    return f"...{key[-4:]}" if len(key) > 4 else "..."
