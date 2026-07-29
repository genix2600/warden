"""The only code in Warden that changes the machine.

Four gates stand between a proposal and a running process, in this order:

1. **Approval.** ``execute`` requires an ``approved_at`` timestamp. There is no
   default, no ``force`` flag and no code path that supplies one on the user's
   behalf. ``tests/test_approval_gate.py`` asserts this by inspecting the
   signature, so it survives refactoring.
2. **Registry membership.** The action id must name a real playbook.
3. **Re-derivation.** The argv is rendered *again*, here, from the registry
   template and the proposal's parameters, and compared against the argv the
   proposal carries. A proposal whose command does not match what the registry
   would produce for those parameters is refused. Nothing downstream of the
   reasoner is trusted to hand us a command -- not even our own earlier self.
4. **Privilege.** An action needing elevation is refused rather than attempted
   when the process is not elevated, so the failure is explained before the user
   commits rather than as an obscure exit code afterwards.

And then, throughout: ``shell=False`` with an argv list. There is no shell in
this process, so there is nothing to inject into.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime
from queue import Empty, Queue

from warden.contracts import (
    ActionProposal,
    ExecutionOutcome,
    ExecutionRecord,
    RiskTier,
    utcnow,
)
from warden.executor.restore import ensure_checkpoint
from warden.playbooks import REGISTRY, ActionRejected, PlaybookRegistry, render_argv
from warden.winenv import is_admin

log = logging.getLogger(__name__)

#: Emitted as the process writes. (stream, text)
OutputSink = Callable[[str, str], None]

_TAIL_CHARS = 4000
#: Nothing in the registry legitimately runs longer than this. A hard ceiling
#: means a wedged command cannot hold an incident open indefinitely.
_MAX_RUNTIME_S = 120.0


class Executor:
    def __init__(self, registry: PlaybookRegistry = REGISTRY) -> None:
        self._registry = registry
        self._checkpointed = False

    def execute(
        self,
        proposal: ActionProposal,
        *,
        approved_at: datetime,
        on_output: OutputSink | None = None,
    ) -> ExecutionRecord:
        """Run an approved proposal. ``approved_at`` is required, deliberately."""
        record = ExecutionRecord(
            proposal_id=proposal.id,
            action_id=proposal.action_id,
            argv=list(proposal.rendered_argv),
            approved_at=approved_at,
        )

        blocked = self._preflight(proposal)
        if blocked is not None:
            record.outcome = ExecutionOutcome.BLOCKED
            record.blocked_reason = blocked
            record.finished_at = utcnow()
            log.warning("refused to execute %s: %s", proposal.action_id, blocked)
            return record

        # A safety net for the whole machine, taken once per session before the
        # first disruptive action rather than before every action -- Windows
        # rate-limits checkpoints to one a day, and a snapshot from earlier in
        # the session still predates everything Warden has done. Best effort: a
        # machine with System Protection switched off is one Warden still works
        # on, and Readiness says plainly that the net is missing.
        if proposal.risk is RiskTier.INTRUSIVE and not self._checkpointed:
            self._checkpointed = True
            state = ensure_checkpoint()
            log.info("restore point before first intrusive action: %s", state.detail)

        return self._run(proposal, record, on_output)

    def _preflight(self, proposal: ActionProposal) -> str | None:
        try:
            playbook = self._registry.get(proposal.action_id)
        except ActionRejected as exc:
            return str(exc)

        try:
            expected = render_argv(playbook.argv_template, proposal.params)
        except ActionRejected as exc:
            return str(exc)

        if expected != proposal.rendered_argv:
            # Either the proposal was built somewhere other than the registry, or
            # it was altered after it was built. Both are refusals.
            return (
                "the command in this proposal does not match what the registry would "
                f"produce for these parameters (expected {expected!r})"
            )

        if playbook.requires_admin and not is_admin():
            return (
                f"{playbook.title!r} needs administrator rights and Warden is running "
                "as a standard user. Restart it elevated to use this fix."
            )
        if playbook.risk is RiskTier.READ_ONLY and not playbook.reversible:
            return "registry inconsistency: a read-only action cannot be irreversible"
        return None

    def _run(
        self,
        proposal: ActionProposal,
        record: ExecutionRecord,
        on_output: OutputSink | None,
    ) -> ExecutionRecord:
        timeout = min(max(proposal.est_duration_s * 3, 15.0), _MAX_RUNTIME_S)
        record.started_at = utcnow()
        log.info("executing %s: %s", proposal.action_id, proposal.rendered_argv)

        try:
            proc = subprocess.Popen(
                proposal.rendered_argv,
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

        stdout, stderr = self._pump(proc, on_output, timeout, record)

        record.stdout_tail = stdout[-_TAIL_CHARS:]
        record.stderr_tail = stderr[-_TAIL_CHARS:]
        record.exit_code = proc.returncode
        record.finished_at = utcnow()
        # The outcome here is only "the command ran and said it worked". Whether
        # the *problem* is fixed is the verifier's call, and the orchestrator
        # overwrites this once the verification result is in.
        record.outcome = (
            ExecutionOutcome.RESOLVED
            if proc.returncode == 0 and not record.timed_out
            else ExecutionOutcome.NOT_RESOLVED
        )
        return record

    @staticmethod
    def _pump(
        proc: subprocess.Popen[str],
        on_output: OutputSink | None,
        timeout: float,
        record: ExecutionRecord,
    ) -> tuple[str, str]:
        """Stream both pipes to the sink, then wait with a hard deadline.

        Reader threads exist because a command that fills its stderr pipe while
        we block on stdout deadlocks, and because the UI shows output as it
        arrives rather than in one lump at the end.
        """
        queue: Queue[tuple[str, str] | None] = Queue()

        def reader(stream: object, name: str) -> None:
            try:
                for line in stream:  # type: ignore[attr-defined]
                    queue.put((name, line.rstrip("\r\n")))
            finally:
                queue.put(None)

        threads = [
            threading.Thread(target=reader, args=(proc.stdout, "stdout"), daemon=True),
            threading.Thread(target=reader, args=(proc.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()

        collected = {"stdout": [], "stderr": []}  # type: dict[str, list[str]]
        finished_streams = 0
        while finished_streams < len(threads):
            try:
                item = queue.get(timeout=timeout)
            except Empty:
                break
            if item is None:
                finished_streams += 1
                continue
            stream, text = item
            collected[stream].append(text)
            if on_output is not None:
                on_output(stream, text)

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            record.timed_out = True
            proc.kill()
            proc.wait(timeout=5)
            log.warning("command exceeded %.0fs and was terminated", timeout)

        return "\n".join(collected["stdout"]), "\n".join(collected["stderr"])
