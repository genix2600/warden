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

2. **No shell, ever.** Same rule as the reviewed path: an argument list, never a
   string, ``shell=False``. A model that wants a pipeline has to be told no.
   This also means the refusal list cannot be defeated by quoting tricks, since
   there is no shell to interpret them.

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
import subprocess
from datetime import datetime

from warden.contracts import ExecutionOutcome, ExecutionRecord, utcnow
from warden.executor.restore import ensure_checkpoint
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

    # A shell invoked with an inline command string reintroduces everything the
    # argv-only rule exists to remove, so it is refused as a shape rather than
    # for anything it happens to contain.
    if program in {"cmd", "powershell", "pwsh"} and any(
        arg.lower() in {"/c", "/k", "-c", "-command"} for arg in argv[1:]
    ):
        return (
            "a command that opens a shell to run another command hides the real "
            "command from this check. Ask for the underlying command instead."
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
        on_output: object | None = None,
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

        return self._run(argv, record)

    def _run(self, argv: list[str], record: ExecutionRecord) -> ExecutionRecord:
        record.started_at = utcnow()
        log.info("executing composed command: %s", argv)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=_MAX_RUNTIME_S,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            record.timed_out = True
            record.outcome = ExecutionOutcome.NOT_RESOLVED
            record.stderr_tail = f"the command was still running after {_MAX_RUNTIME_S:.0f}s"
            record.finished_at = utcnow()
            return record
        except (OSError, ValueError) as exc:
            record.outcome = ExecutionOutcome.ERROR
            record.stderr_tail = f"could not start the command: {exc}"
            record.finished_at = utcnow()
            return record

        record.stdout_tail = proc.stdout[-_TAIL_CHARS:]
        record.stderr_tail = proc.stderr[-_TAIL_CHARS:]
        record.exit_code = proc.returncode
        record.finished_at = utcnow()
        # Exit code only. Warden measured `netsh wlan connect` returning zero on
        # a reconnect that never happened, so this is "the command ran" and
        # nothing more. A composed command has no declared predicate, so the
        # honest report is the output plus the model's own check, shown to the
        # user rather than converted into a verdict Warden cannot support.
        record.outcome = (
            ExecutionOutcome.RESOLVED
            if proc.returncode == 0
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
