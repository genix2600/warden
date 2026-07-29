"""Thin, honest wrappers around the Windows facts Warden needs about itself."""

from __future__ import annotations

import ctypes
import functools
import platform
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a source checkout.

    Warden answers two questions differently depending on this: where its
    read-only assets live, and where it is allowed to write. Both are settled in
    ``warden.paths``; this is the single place the question itself is asked.
    """
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def is_admin() -> bool:
    """True when the process holds an elevated token.

    Checked before proposing anything that needs it, so the approval card can say
    "this needs administrator and you don't have it" instead of failing after the
    user has already said yes.
    """
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


#: Windows 11 reports itself as Windows 10 through every documented API; the
#: build number is the only thing that distinguishes them. 22000 is the first
#: Windows 11 build.
_WINDOWS_11_BUILD = 22000


def windows_release() -> str:
    """The release name a human would recognise.

    ``platform.release()`` returns "10" on Windows 11, because Microsoft never
    changed the major version. Reporting "Windows 10" to a user sitting in front
    of Windows 11 undermines confidence in every other reading on the screen, so
    it is worth the six lines to get right.
    """
    release = platform.release()
    if release == "10":
        try:
            build = int(platform.version().split(".")[-1])
        except (ValueError, IndexError):
            return release
        if build >= _WINDOWS_11_BUILD:
            return "11"
    return release


@functools.cache
def describe_host() -> dict[str, str]:
    """Static machine facts, cached. Shown in the UI footer and the session log."""
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {windows_release()}" if is_windows() else platform.system(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "elevated": str(is_admin()).lower(),
    }
