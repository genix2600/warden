import { useState } from "react";
import type { ActionProposal } from "../types";
import { renderArgv, riskLabel } from "../lib/format";
import { ElevateButton } from "./ElevateButton";
import { Pill } from "./StatusDot";

/**
 * The approval gate, as the user experiences it.
 *
 * Three things are on this card before anyone can say yes: the exact command,
 * character for character; what it will do to the machine, in plain words; and
 * the test that will decide whether it worked. The last one matters most --
 * approving a fix also means approving the standard it will be judged by, so
 * "it's fixed" afterwards is a measurement the user already agreed to rather
 * than a claim they have to take on faith.
 */
export function ProposalCard({
  proposal,
  onApprove,
  onDecline,
  busy,
  elevated,
}: {
  proposal: ActionProposal;
  onApprove: () => void;
  onDecline: (mute: boolean) => void;
  busy: boolean;
  elevated: boolean;
}) {
  const [error, setError] = useState<string | null>(null);

  const guarded = async (run: () => Promise<void>) => {
    setError(null);
    try {
      await run();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  };

  const risk = proposal.risk;
  const tone = risk === "intrusive" ? "warning" : risk === "read_only" ? "good" : "idle";

  return (
    <section className="rise rounded-xl border border-warning/40 bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-3">
        <h3 className="text-sm font-semibold text-ink">Warden wants to run one command</h3>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <Pill tone={tone}>{riskLabel(risk)}</Pill>
          {proposal.requires_admin && <Pill tone="warning">Needs administrator</Pill>}
          {proposal.reversible && <Pill tone="good">Undoable</Pill>}
        </div>
      </header>

      <div className="space-y-4 p-4">
        <div>
          <Label>The command, exactly as it will run</Label>
          <code className="mt-1.5 block overflow-x-auto rounded-lg bg-sunken p-3 font-mono text-[13px] leading-relaxed text-ink select-all">
            <span className="text-muted">&gt; </span>
            {renderArgv(proposal.rendered_argv)}
          </code>
          <p className="mt-1.5 text-[11px] text-muted">
            Passed to Windows as separate arguments, never through a shell. Nothing else runs.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label>What it does</Label>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
              {proposal.expected_effect}
            </p>
          </div>
          <div>
            <Label>How we will know it worked</Label>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
              {proposal.verify.predicate.describe}
            </p>
          </div>
        </div>

        <div>
          <Label>Why this action</Label>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{proposal.rationale}</p>
        </div>

        {/* The executor would refuse this after approval, which is a dead end
            the user can do nothing with. Say it before they commit, and put the
            remedy next to the sentence. */}
        {proposal.requires_admin && !elevated && (
          <div className="rounded-lg border border-warning/40 bg-warning/5 p-3">
            <p className="text-[12px] leading-relaxed text-ink-2">
              This fix needs administrator rights, and Warden is running as a standard
              user. Everything else on this page still works. Restart elevated and the
              same proposal will be waiting.
            </p>
            <ElevateButton compact />
          </div>
        )}

        {error && (
          <p className="rounded border border-critical/40 bg-critical/10 p-2.5 text-[12px] text-critical">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            disabled={busy}
            onClick={() => void guarded(async () => onApprove())}
            className="rounded-lg bg-series-1 px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Running…" : "Approve and run"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void guarded(async () => onDecline(false))}
            className="rounded-lg border border-hairline px-4 py-2 text-sm font-medium text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            No thanks
          </button>
          {/* Some findings are not faults on this machine: a network kept
              Public on purpose, a clock that is right but has no time server to
              prove it. Declining alone meant asking again later, which over a
              working day is nagging, and nagging about a decision already made
              is how a tool teaches people to ignore it. */}
          <button
            type="button"
            disabled={busy}
            onClick={() => void guarded(async () => onDecline(true))}
            title="Warden keeps detecting this and keeps showing it on Health. It stops proposing a fix."
            className="rounded-lg border border-hairline px-3 py-2 text-[12px] text-muted transition-colors hover:bg-raised hover:text-ink-2 disabled:opacity-50"
          >
            No, and stop asking
          </button>
          <span className="ml-auto text-[11px] text-muted">
            Nothing happens until you choose. Warden will wait indefinitely.
          </span>
        </div>
      </div>
    </section>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
      {children}
    </span>
  );
}
