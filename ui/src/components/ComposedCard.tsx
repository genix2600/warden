import type { ComposedCommand } from "../types";
import { renderArgv } from "../lib/format";
import { StatusDot } from "./StatusDot";

/**
 * A command the cloud model wrote, which is not the same thing as a fix.
 *
 * ProposalCard renders something from the reviewed registry: a person read it,
 * its arguments were checked against readings actually taken from this machine,
 * and it declares in advance the test that will decide whether it worked. None
 * of that is true here. The command was written seconds ago by a model that has
 * never seen this computer, and the only automated check it has passed is that
 * it is not on a list of things Warden refuses outright.
 *
 * So this deliberately does not look like a ProposalCard. Same information
 * architecture, different colour, a different verb on the button, and a line
 * that says plainly what Warden does and does not know about it. A user who
 * cannot tell the two apart at a glance has been misled by the interface, and
 * the whole argument for allowing composed commands at all rests on them being
 * able to.
 */
export function ComposedCard({
  command,
  busy,
  elevated,
  onApprove,
  onDecline,
}: {
  command: ComposedCommand;
  busy: boolean;
  elevated: boolean;
  onApprove: () => void;
  onDecline: () => void;
}) {
  // Refused before anyone was asked. Showing a destructive command next to a
  // confident explanation and an approve button is not consent, so there is no
  // button on this branch at all.
  if (command.refused) {
    return (
      <section className="rounded-xl border border-critical/50 bg-surface p-4">
        <div className="mb-2 flex items-center gap-2">
          <StatusDot tone="critical" />
          <h2 className="text-sm font-semibold text-ink">Warden refused this command</h2>
        </div>
        <code className="block overflow-x-auto rounded-lg bg-sunken p-2.5 font-mono text-[12px] leading-relaxed text-muted line-through">
          {renderArgv(command.argv)}
        </code>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{command.refused}</p>
        <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
          The model wrote this and Warden will not run it. You were not asked to approve
          it, because a good explanation beside a bad command is how this goes wrong.
        </p>
      </section>
    );
  }

  const disruptive = command.risk === "disruptive";

  return (
    <section className="rounded-xl border border-warning/50 bg-surface p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <StatusDot tone="warning" />
        <h2 className="text-sm font-semibold text-ink">
          The cloud model wrote this command
        </h2>
        <span className="rounded border border-warning/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
          Not from the reviewed list
        </span>
      </div>

      <code className="block overflow-x-auto rounded-lg bg-sunken p-2.5 font-mono text-[12px] leading-relaxed text-ink">
        <span className="text-muted">&gt; </span>
        {renderArgv(command.argv)}
      </code>

      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="What it does">{command.explain}</Field>
        <Field label="What it changes">{command.changes}</Field>
        <Field label={command.reversible ? "How to undo it" : "Can this be undone"}>
          {command.reversible
            ? command.undo || "The model did not say, which is a reason to be careful."
            : "No. This cannot be reversed."}
        </Field>
        <Field label="How you will know">
          {command.check || "The model did not say."}
        </Field>
      </dl>

      {/* The honest difference, stated where the decision is made rather than
          buried on the Model page. */}
      <p className="mt-3 rounded-lg bg-sunken px-3 py-2.5 text-[12px] leading-relaxed text-ink-2">
        Warden did not write this and has not verified it. Its seventeen reviewed
        actions are checked against what was measured on this machine and re-tested
        afterwards; this one is checked only against a list of things Warden refuses
        outright. Read the command before you approve it.
      </p>

      {command.requires_admin && !elevated && (
        <p className="mt-2 text-[12px] leading-relaxed text-critical">
          This needs administrator rights and Warden is running as a standard user.
          Restart it elevated from the Readiness page first.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApprove}
          disabled={busy || (command.requires_admin && !elevated)}
          className={`rounded-lg px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40 ${
            disruptive ? "bg-serious" : "bg-series-1"
          }`}
        >
          {busy ? "Running…" : "Run this command"}
        </button>
        <button
          type="button"
          onClick={onDecline}
          disabled={busy}
          className="rounded-lg border border-hairline px-4 py-2 text-[13px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
        >
          No
        </button>
        <span className="text-[12px] text-muted">
          Nothing happens until you choose. Warden will wait indefinitely.
        </span>
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </dt>
      <dd className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{children}</dd>
    </div>
  );
}
