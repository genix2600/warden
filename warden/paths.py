"""Where Warden's files live, answered in one place.

Until this module existed every path in the codebase was relative to the current
working directory. That is invisible during development, because the working
directory is always the repository root -- and fatal once the application is
frozen, because the working directory becomes whatever folder the user happened
to double-click from.

The distinction that matters is not "development versus frozen" but **read-only
versus writable**:

``resource_path``
    Things shipped *with* Warden and never modified: the built interface, replay
    fixtures, the optional sensor DLL. Inside a bundle these are extracted to a
    temporary directory that PyInstaller advertises as ``sys._MEIPASS``, and
    writing there would be silently discarded on exit.

``data_path``
    Things belonging to *this user on this machine*: recorded sessions, local
    threshold overrides. These must survive an upgrade and must not require the
    install directory to be writable, which under ``C:\\Program Files`` it is not.

In a source checkout both resolve into the repository, so every existing
workflow, test and ``run.ps1`` invocation behaves exactly as it did before.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from warden.winenv import is_frozen

#: The checkout root: ``warden/paths.py`` -> ``warden/`` -> the repository.
#: Only consulted when running from source, where ``__file__`` is a real file.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _bundle_root() -> Path:
    """The directory PyInstaller extracted the bundled assets into."""
    return Path(getattr(sys, "_MEIPASS", _REPO_ROOT))


def _user_root() -> Path:
    """The per-user data directory, ``%LOCALAPPDATA%\\Warden``.

    ``LOCALAPPDATA`` is absent under some service accounts and on non-Windows
    machines running the test suite, so it is read defensively rather than
    indexed -- a ``KeyError`` at import time would take the whole application
    down over a directory that is only needed if something is written.
    """
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local:
        return Path(local) / "Warden"
    return Path.home() / ".warden"


def resource_path(*parts: str) -> Path:
    """Locate a read-only asset shipped with Warden."""
    return (_bundle_root() if is_frozen() else _REPO_ROOT).joinpath(*parts)


def data_path(*parts: str) -> Path:
    """Locate a writable per-user file or directory.

    The directory is *not* created here. Import-time filesystem side effects are
    how a test suite ends up depending on the order its modules were loaded in;
    creation belongs to whoever actually writes.
    """
    return (_user_root() if is_frozen() else _REPO_ROOT).joinpath(*parts)
