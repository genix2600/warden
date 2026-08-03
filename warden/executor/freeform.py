"""Running a command the model wrote, which is a different problem entirely.

:mod:`warden.executor.runner` is safe because of something it does not have to
decide: the command already exists in a reviewed registry, so the only question
is whether *this* proposal matches *that* entry. Four cheap comparisons answer
it, and none of them require understanding what the command does.

Nothing here can lean on that. The command arrives from a hosted model, has
never been read by a person, and the only thing standing between it and the
machine is this file plus a human clicking a button. So the gates are different
in kind:

1. **A refusal list, checked first.** Not an attempt to decide whether an
   arbitrary command is safe, which is undecidable and would be a lie to
   attempt. It is a list of specific things Warden will not run whatever the
   justification: wiping a disk, deleting shadow copies so a restore becomes
   impossible, switching off Defender, downloading and executing something,
   creating an account. These are refused before the user is ever shown an
   approve button, because a good enough explanation next to a bad enough
   command is exactly how this goes wrong.

2. **Readable, rather than uninterpreted.** Same rule as the reviewed path: an
   argument list, never a string, ``shell=False``, so the refusal list cannot be
   defeated by quoting tricks. That is not the same as banning interpreters, and
   an earlier version of this file confused the two -- refusing every
   ``powershell -Command``, which is precisely how all seventeen reviewed
   actions are written, because most of what fixes Windows is a cmdlet rather
   than an executable. The test that survives is whether the person clicking
   approve can read what will run: a cmdlet written out passes, a base64 payload
   or a script that assembles itself does not.

3. **Approval that cannot be defaulted.** ``approved_at`` is keyword-only with
   no default, exactly as in the reviewed runner, so forgetting it is a type
   error rather than a silent execution.

4. **A restore point first.** Anything that is not read-only takes a checkpoint
   before it runs, not once per session. The reviewed actions earned the
   once-per-session optimisation by being reviewed.

What this deliberately does **not** do is claim the result is safe. It claims
the result is *visible*: the exact argv, what the model says it changes, whether
it can be undone, and how to undo it, all on screen before anything happens.
That is a weaker promise than the registry makes, and the interface says so
rather than blurring the two.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from datetime import datetime

from warden.contracts import ExecutionOutcome, ExecutionRecord, utcnow
from warden.executor.restore import ensure_checkpoint
from warden.executor.runner import Executor, OutputSink
from warden.winenv import is_admin

log = logging.getLogger(__name__)

_TAIL_CHARS = 4000
_MAX_RUNTIME_S = 120.0

#: Executables Warden will not launch from a model-written command at all.
#:
#: Each of these has a legitimate administrative use and none of them has one
#: *here*. A diagnostician does not need to repartition a disk, rewrite the boot
#: configuration, or schedule something to run later, and a model that thinks it
#: does has misunderstood the problem badly enough that the right answer is to
#: stop rather than to ask more politely.
_REFUSED_PROGRAMS = frozenset(
    {
        "format",
        "diskpart",
        "bcdedit",
        "bootsect",
        "bootrec",
        "fdisk",
        "vssadmin",
        "wbadmin",
        "cipher",
        "schtasks",
        "at",
        "bitsadmin",
        "certutil",
        "regsvr32",
        "rundll32",
        "mshta",
        "wmic",
        "psexec",
        "takeown",
    }
)

#: Patterns refused wherever they appear in the argument list.
#:
#: Matched against the arguments joined by spaces and lowercased, purely as a
#: readability aid: there is no shell, so this is not defending against quoting,
#: only against a command that plainly says what it is going to do.
_REFUSED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bdelete[\s\-]+shadows?\b|\bshadowcopy[\s\-]+delete\b"),
        "deleting shadow copies would remove the restore points that make "
        "everything else here reversible",
    ),
    (
        re.compile(r"-disablerealtimemonitoring|\bdisableantispyware\b|\bmppreference\b"),
        "switching off Defender is not a repair, and Warden will not do it",
    ),
    (
        re.compile(r"advfirewall\s+set\s+\w+\s+state\s+off|firewallpolicy.*blockinbound.*allow"),
        "turning the firewall off wholesale trades a real protection for a "
        "diagnosis that can be reached another way",
    ),
    (
        # Not `\b-enc`: a word boundary needs a word character on one side, and
        # both the space and the hyphen are non-word, so that pattern silently
        # matched nothing. Caught by the test, which is why the test exists.
        re.compile(r"(?:^|\s)-e(?:nc|ncodedcommand)\b"),
        "a base64-encoded command hides what it does from the person approving it",
    ),
    (
        re.compile(r"\b(iex|invoke-expression)\b|downloadstring|invoke-webrequest.*\|"),
        "downloading and running code is not something Warden will do on your behalf",
    ),
    (
        re.compile(r"\bnet\s+user\b.*\s/add|\blocalgroup\b.*administrators.*\s/add"),
        "creating an account or granting administrator rights is not a repair",
    ),
    (
        re.compile(r"\brd\s+/s|\brmdir\s+/s|\bdel\s+/[sq]\b.*\\windows|remove-item.*-recurse.*"
                   r"(windows|system32|program files)"),
        "recursively deleting a system directory cannot be undone",
    ),
    (
        re.compile(r"\breg\s+delete\s+hk(lm|ey_local_machine)\\?(software|system)?\s*/f\s*$"),
        "deleting a registry hive wholesale is not recoverable",
    ),
    (
        re.compile(r"\bcurl\b.*\|\s*(cmd|powershell|sh)|\bwget\b.*\|\s*(cmd|powershell|sh)"),
        "piping a download into an interpreter is the shape of an attack, not a fix",
    ),
)


class RefusedCommand(Exception):
    """Warden will not run this, and the user is never asked about it."""


def screen(argv: list[str]) -> str | None:
    """Return why this command is refused, or None if it may be offered.

    Called before the user sees an approve button, which is the whole point.
    Showing someone a destructive command alongside a confident explanation and
    asking them to judge it is not consent, it is a trap.
    """
    if not argv:
        return "the model produced an empty command"

    program = argv[0].lower().rsplit("\\", 1)[-1].removesuffix(".exe")
    if program in _REFUSED_PROGRAMS:
        return (
            f"{program!r} is not something Warden will run from a command the model "
            f"wrote. It has legitimate uses and none of them are diagnosing a fault."
        )

    joined = " ".join(argv).lower()
    for pattern, reason in _REFUSED_PATTERNS:
        if pattern.search(joined):
            return reason

    if program in {"cmd", "powershell", "pwsh"}:
        return _screen_interpreter(argv[1:])

    missing = _not_on_this_machine(argv[0])
    if missing is not None:
        return missing
    return None


def _not_on_this_machine(program: str) -> str | None:
    """Whether the executable exists at all, which is not the same as safe.

    Every other check here asks whether a command should run. This one asks
    whether it *can*, and it exists because a model will occasionally write a
    command that has never existed. Measured, asked about Wi-Fi dropping out:
    `netsh wlan reset networkstate`, which produces "The following command was
    not found".

    Refusing rather than warning, because the alternative is asking someone to
    approve a command that cannot possibly work and then showing them a Windows
    error they have no way to interpret. A refusal instead goes back to the
    model with the reason, which is the loop that already exists.

    Two honest limits. This checks the *program*, not its arguments, so the
    measured `netsh wlan reset networkstate` still passes -- `netsh` is real.
    And it cannot see PowerShell cmdlets, which are resolved by the interpreter
    rather than by the filesystem. For both, the safety net is the same one a
    wrong-but-real command gets: it fails, and its output goes back to the model.
    """
    if shutil.which(program) is not None:
        return None
    return (
        f"{program!r} is not a program on this machine, so this command cannot "
        f"run. Models occasionally write commands that have never existed, and "
        f"running one only produces an error nobody can act on."
    )


#: Published short forms for ``-EncodedCommand`` that are *not* prefixes of it.
#:
#: This set exists because prefix matching alone is not how PowerShell resolves
#: parameters, and assuming it was left a hole. ``-ec`` is the published alias
#: for ``-EncodedCommand`` and ``"encodedcommand".startswith("ec")`` is false,
#: so a rule built purely on prefixes let ``powershell -ec <base64>`` through --
#: the single most useful thing to smuggle past a check whose whole purpose is
#: that the person approving can read what will run.
_ENCODED_ALIASES = frozenset({"ec", "ec:"})

#: Switches after which the remaining arguments are code, not parameters.
_INLINE_SWITCHES = frozenset({"c", "k", "command", "/c", "/k"})

#: Things that can appear inside an inline script and make it unreadable.
#:
#: The distinction this whole check now turns on is *opacity*, not
#: interpretation. A script that says what it does can be read by the person
#: approving it; one that assembles itself at runtime cannot, and no amount of
#: staring at the argv will reveal what it is going to do.
_OPAQUE_SCRIPT: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\[\s*scriptblock\s*\]\s*::\s*create|\biex\b|invoke-expression"),
        "this command builds another command at runtime, so what would actually "
        "run cannot be read before approving it",
    ),
    (
        re.compile(r"frombase64string|\[convert\]\s*::\s*from"),
        "this command decodes its real contents at runtime, which hides them "
        "from the person approving it",
    ),
    (
        re.compile(r"\b(?:cmd|powershell|pwsh)(?:\.exe)?\s+[-/](?:c|k|e|en|enc|ec|command)\b"),
        "this command starts a second interpreter, which puts the real work one "
        "level further away from the person reading it",
    ),
)

#: How many statements may share one command before it stops being a command.
#:
#: Three covers the fixes that genuinely need a sequence -- stop a service,
#: clear its state, start it again -- and stops short of a script, where the
#: consequential line can sit in the middle and be skimmed past.
_MAX_STATEMENTS = 3


def _screen_interpreter(args: list[str]) -> str | None:
    """Why this interpreter invocation is refused, or None if it may be offered.

    The rule here used to be "an interpreter with an inline command string is
    refused, as a shape". That was wrong in a way that only showed up against a
    real model: **it refused the exact shape Warden itself ships.** Every one of
    the seventeen reviewed actions renders as ``powershell.exe -NoProfile
    -NonInteractive -ExecutionPolicy Bypass -Command <script>``, because most of
    what fixes Windows is a cmdlet and a cmdlet has no executable to invoke.
    ``Restart-Service`` is not a program. There is no ``restart-service.exe``.

    So the old rule did not raise the bar, it removed the feature: asked about
    Bluetooth, the model correctly wrote ``Restart-Service bthserv``, and Warden
    refused it with the sentence "a command that opens a shell to run another
    command hides the real command from this check" -- which was also simply
    untrue. Nothing was hidden. The script was right there in the argv, fully
    readable, and already screened by every pattern above.

    What actually matters is whether the person clicking approve can see what
    will run. That fails for encoded payloads and for scripts that assemble
    themselves, and it does not fail for a cmdlet written out in the open. This
    checks for the former and permits the latter.

    ``-File`` needs no check at all: a script on disk is something the user can
    open and read, which is the property being protected.
    """
    index = 0
    while index < len(args):
        token = args[index].lstrip("-/").lower()
        index += 1
        if not token:
            continue

        # Encoded, under any of the several spellings that reach it. Refused
        # outright: base64 is not something a person can read at an approval
        # prompt, whatever it decodes to.
        if token in _ENCODED_ALIASES or "encodedcommand".startswith(token):
            return (
                "this command is base64-encoded, so the person approving it cannot "
                "read what it does. Ask for it in plain text instead."
            )

        if token in _INLINE_SWITCHES or (token and "command".startswith(token)):
            # PowerShell treats everything after -Command as the script.
            return _hides_its_work(" ".join(args[index:]))

    return None


def _hides_its_work(script: str) -> str | None:
    """Why this inline script cannot be read at an approval prompt."""
    if not script.strip():
        return "the model asked for an interpreter but gave it nothing to run"

    lowered = script.lower()
    for pattern, reason in _OPAQUE_SCRIPT:
        if pattern.search(lowered):
            return reason

    statements = [part for part in re.split(r";|\r?\n", script) if part.strip()]
    if len(statements) > _MAX_STATEMENTS:
        return (
            f"this is a script of {len(statements)} statements rather than a "
            f"command. Warden runs one fix at a time so that the line that "
            f"matters cannot be skimmed past. Ask for the smallest step first."
        )
    return None


class FreeformExecutor:
    """Runs model-written commands, having refused the ones it will not."""

    def execute(
        self,
        argv: list[str],
        *,
        approved_at: datetime,
        reads_only: bool = False,
        on_output: OutputSink | None = None,
    ) -> ExecutionRecord:
        """Run an approved, model-written command. ``approved_at`` is required."""
        record = ExecutionRecord(
            proposal_id="composed",
            action_id="cloud.composed",
            argv=list(argv),
            approved_at=approved_at,
        )

        refusal = screen(argv)
        if refusal is not None:
            record.outcome = ExecutionOutcome.BLOCKED
            record.blocked_reason = refusal
            record.finished_at = utcnow()
            log.warning("refused a composed command %r: %s", argv, refusal)
            return record

        if not reads_only:
            # Every time, not once per session. The reviewed actions earned that
            # optimisation by having been read by a person first.
            state = ensure_checkpoint()
            log.info("restore point before composed command: %s", state.detail)

        return self._run(argv, record, on_output)

    def _run(
        self,
        argv: list[str],
        record: ExecutionRecord,
        on_output: OutputSink | None,
    ) -> ExecutionRecord:
        """Run it, streaming both pipes as they fill.

        This used to be a `subprocess.run` that captured everything and handed
        it back at the end, and the `on_output` parameter beside it was dead.
        For a reviewed action that would merely be a downgrade; here it is worse,
        because a composed command is the one case where the user has the least
        idea what is about to happen and most needs to watch it happen. `sfc
        /scannow` runs for minutes and prints progress the whole time, and a
        blank panel until it finishes is indistinguishable from a hang.

        The pump is the reviewed runner's, unchanged: two reader threads, since
        a command that fills stderr while we block on stdout deadlocks.
        """
        record.started_at = utcnow()
        log.info("executing composed command: %s", argv)
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as exc:
            record.outcome = ExecutionOutcome.ERROR
            record.stderr_tail = f"could not start the command: {exc}"
            record.finished_at = utcnow()
            return record

        stdout, stderr = Executor._pump(proc, on_output, _MAX_RUNTIME_S, record)

        record.stdout_tail = stdout[-_TAIL_CHARS:]
        record.stderr_tail = stderr[-_TAIL_CHARS:]
        record.exit_code = proc.returncode
        record.finished_at = utcnow()
        # Exit code only. Warden measured `netsh wlan connect` returning zero on
        # a reconnect that never happened, so this is "the command ran" and
        # nothing more. A composed command has no declared predicate, so the
        # honest report is the output plus the model's own check, shown to the
        # user rather than converted into a verdict Warden cannot support.
        record.outcome = (
            ExecutionOutcome.RESOLVED
            if proc.returncode == 0 and not record.timed_out
            else ExecutionOutcome.NOT_RESOLVED
        )
        return record


def needs_admin_but_lacks_it(command_requires_admin: bool) -> str | None:
    """Say so up front rather than letting the command fail confusingly."""
    if command_requires_admin and not is_admin():
        return (
            "this needs administrator rights and Warden is running as a standard "
            "user. Restart it elevated from the Readiness page first."
        )
    return None
