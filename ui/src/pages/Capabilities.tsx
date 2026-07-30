import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { renderArgv, riskLabel } from "../lib/format";
import type { ActionSpec, CapabilityReport } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Pill } from "../components/StatusDot";

/**
 * Everything Warden is capable of doing to this machine, and everything it has
 * decided it cannot.
 *
 * This page exists because a tool asking for permission to run commands should
 * be able to state its own limits precisely, before it is asked. The list is
 * complete -- it is rendered from the same registry the executor validates
 * against, so it cannot flatter itself by omission.
 */
export function Capabilities() {
  const [report, setReport] = useState<CapabilityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api
      .actions()
      .then(setReport)
      .catch((problem: unknown) =>
        setError(problem instanceof Error ? problem.message : String(problem)),
      );
  }, []);

  const byRisk = (risk: string) => report?.actions.filter((a) => a.risk === risk) ?? [];
  const groups = [
    {
      risk: "read_only",
      title: "Looks, changes nothing",
      blurb: "Gathers more information. Cannot alter the machine even if it wanted to.",
    },
    {
      risk: "reversible",
      title: "Changes something, easily undone",
      blurb: "Reconnects, clears a cache, corrects a setting. Nothing here is hard to reverse.",
    },
    {
      risk: "intrusive",
      title: "Disruptive while it runs",
      blurb:
        "Restarts a device or service, or changes a startup setting. You will notice these happen.",
    },
  ];

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="What Warden can do"
        subtitle={
          report
            ? `${report.actions.length} actions in total, and ${report.symptoms_with_no_software_fix.length} problems it has decided it cannot fix. This is the complete list. There is no other way for it to change your machine.`
            : "Loading the full action list…"
        }
      />

      {error && <p className="text-[13px] text-critical">{error}</p>}

      {report && (
        <>
          {groups.map((group) => {
            const actions = byRisk(group.risk);
            if (actions.length === 0) return null;
            return (
              <section key={group.risk} className="mb-6">
                <h2 className="text-[13px] font-semibold text-ink">{group.title}</h2>
                <p className="mb-2.5 text-[12px] text-muted">{group.blurb}</p>
                <div className="space-y-2">
                  {actions.map((action) => (
                    <ActionRow
                      key={action.id}
                      action={action}
                      expanded={open === action.id}
                      onToggle={() => setOpen(open === action.id ? null : action.id)}
                    />
                  ))}
                </div>
              </section>
            );
          })}

          <section className="rounded-xl border border-serious/40 bg-surface p-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-serious">
                <Icon name="shield" size={18} />
              </span>
              <h2 className="text-[14px] font-semibold text-ink">
                Problems Warden will not try to fix
              </h2>
            </div>
            <p className="mb-3 max-w-3xl text-[12px] leading-relaxed text-ink-2">
              These are physical or upstream problems. There is no command in the list above
              that helps, so Warden does not offer one. It explains what it found and who
              needs to act. This is enforced in the code, not by good intentions: for these
              problems the set of available actions is empty, so nothing can select one.
            </p>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {report.symptoms_with_no_software_fix.map((code) => (
                <li
                  key={code}
                  className="flex items-center gap-2 rounded border border-hairline bg-sunken px-2.5 py-1.5"
                >
                  <span aria-hidden className="text-serious text-[11px]">
                    ▲
                  </span>
                  <span className="font-mono text-[11px] text-ink-2">{code}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

function ActionRow({
  action,
  expanded,
  onToggle,
}: {
  action: ActionSpec;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <article className="rounded-lg border border-hairline bg-surface">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[13px] font-medium text-ink">{action.title}</h3>
            {action.requires_admin && <Pill tone="warning">needs administrator</Pill>}
            {!action.reversible && <Pill tone="critical">not reversible</Pill>}
          </div>
          <p className="mt-0.5 text-[12px] leading-snug text-ink-2">{action.summary}</p>
        </div>
        <span className="shrink-0 text-muted">
          <Icon name={expanded ? "check" : "list"} size={14} />
        </span>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-hairline p-3 pt-3">
          <Field label="When Warden considers this">{action.when_to_use}</Field>
          <Field label="The command it would run">
            <code className="mt-1 block overflow-x-auto rounded bg-sunken p-2.5 font-mono text-[11px] leading-relaxed text-ink-2">
              {renderArgv(action.argv_template)}
            </code>
            <p className="mt-1 text-[10px] text-muted">
              Values in braces are filled in from readings taken on your machine, and checked
              against what was actually observed before anything runs.
            </p>
          </Field>
          <Field label="How it proves it worked">{action.verify.predicate.describe}</Field>
          <div className="flex flex-wrap gap-1.5">
            <Pill tone="idle">{riskLabel(action.risk)}</Pill>
            <Pill tone="idle">about {action.est_duration_s}s</Pill>
          </div>
        </div>
      )}
    </article>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </span>
      <div className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}
