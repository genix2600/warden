"""The read-only/writable split, exercised on both sides of the frozen boundary.

These tests exist because the failure they guard against is invisible in
development: every path resolves correctly from a source checkout no matter how
it is computed, and only stops working once the application is packaged, on a
machine that is not this one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from warden import paths
from warden.winenv import is_frozen


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Impersonate a PyInstaller bundle extracted into ``tmp_path``."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return bundle


def test_not_frozen_when_running_from_source() -> None:
    assert not is_frozen()


def test_source_checkout_keeps_everything_in_the_repository() -> None:
    """The development layout must not change; run.ps1 and the tests rely on it."""
    repo = Path(__file__).resolve().parent.parent
    assert paths.resource_path("fixtures") == repo / "fixtures"
    assert paths.data_path("sessions") == repo / "sessions"


def test_frozen_reads_assets_from_the_bundle(frozen: Path) -> None:
    assert is_frozen()
    assert paths.resource_path("ui", "dist") == frozen / "ui" / "dist"


def test_frozen_writes_outside_the_bundle(frozen: Path, tmp_path: Path) -> None:
    """The bundle is a temporary directory; anything written there is lost."""
    sessions = paths.data_path("sessions")
    assert sessions == tmp_path / "appdata" / "Warden" / "sessions"
    assert frozen not in sessions.parents


def test_paths_diverge_only_once_frozen(frozen: Path) -> None:
    assert paths.resource_path("x").parent != paths.data_path("x").parent


def test_data_path_survives_a_missing_localappdata(
    frozen: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Service accounts and CI containers do not always have it set."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert paths.data_path("sessions") == Path.home() / ".warden" / "sessions"


def test_data_path_does_not_touch_the_filesystem(frozen: Path) -> None:
    """Import-time side effects are how test suites become order-dependent."""
    assert not paths.data_path("sessions").exists()


class TestWindowedOutput:
    """A build with no console must still be able to say why it failed.

    PyInstaller's ``console=False`` leaves ``sys.stdout`` and ``sys.stderr`` set
    to None. Warden crashed on launch this way once: uvicorn's colour formatter
    called ``sys.stdout.isatty()`` while building its logging config, and the
    application died before the window appeared, with the traceback going
    nowhere because there was nowhere for it to go.
    """

    def test_absent_streams_are_replaced_with_a_log_file(
        self, frozen: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from warden.__main__ import _redirect_output_to_a_log_file

        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        path = _redirect_output_to_a_log_file()

        assert path is not None and path.exists()
        assert sys.stdout is not None and sys.stderr is not None
        # The specific call that brought the application down.
        assert sys.stdout.isatty() is False
        sys.stdout.close()

    def test_a_real_console_is_left_alone(self) -> None:
        """Running from a terminal, output must keep going to the terminal."""
        from warden.__main__ import _redirect_output_to_a_log_file

        assert _redirect_output_to_a_log_file() is None
