import { useState } from "react";
import { renderArgv, since, stateLabel, stateTone } from "../lib/format";
import { isTerminal } from "../lib/useWarden";
import type { Incident } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Pill, StatusDot } from "../components/StatusDot";

/**
 * What Warden has actually done, and what came of it.
 *
 * Failed attempts are shown as prominently as successful ones. A tool that only
 * displays its wins is a tool you cannot calibrate, and the escalation ladder --
 * try this, it did not work, try the next thing -- only makes sense if you can
 * see the step that failed.
 */
export function History({ incidents }: { incidents: Incident[] }) {
  const [open, setOpen] = useState<string | null>(incidents[0]?.id ?? null);
  const resolved = incidents.filter((i) => i.state === "resolved").length;
  const acted = incidents.filter((i) => i.execution).length;

  if (incidents.length === 0) {
    return (
      <div className="scroll-y h-full px-6 py-5">
        <PageHeader title="History" />
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="History"
        subtitle={
          `${incidents.length} thing${incidents.length === 1 ? "" : "s"} noticed so far. ` +
          `${acted} needed a command run, ${resolved} ended up fixed and verified.`
        }
      />
      <ol className="space-y-2">
        {incidents.map((incident) => (
          <IncidentRow
            key={incident.id}
            incident={incident}
            expanded={open === incident.id}
            onToggle={() => setOpen(open === incident.id ? null : incident.id)}
          />
        ))}
      </ol>
    </div>
  );
}

function IncidentRow({
  incident,
  expanded,
  onToggle,
}: {
  incident: Incident;
  expanded: boolean;
  onToggle: () => void;
}) {
  const tone = stateTone(incident.state);
  const execution = incident.execution;
  const verification = execution?.verification;
  const attempts = incident.attempted_actions.length;

  return (
    <li className="rounded-lg border border-hairline bg-surface">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <span className="mt-0.5">
          <StatusDot tone={tone} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-[13px] font-medium text-ink">{incident.title}</h3>
            <span className="text-[11px] text-muted">{since(incident.opened_at)}</span>
            {!isTerminal(incident.state) && <Pill tone="warning">still open</Pill>}
            {attempts > 0 && (
              <Pill tone="idle">
                {attempts + 1} attempt{attempts === 0 ? "" : "s"}
              </Pill>
            )}
          </div>
          <p className="mt-0.5 text-[12px] text-ink-2">
            {stateLabel(incident.state)}
            {verification ? ` — ${verification.detail}` : ""}
          </p>
        </div>
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-hairline p-3">
          {incident.diagnosis && (
            <>
              <Section label="What Warden concluded">
                {incident.diagnosis.summary}
                <span className="ml-2 text-[11px] text-muted">
                  ({incident.diagnosis.reasoner.mode === "llm" ? "local model" : "rules engine"})
                </span>
              </Section>

              {incident.diagnosis.service_advice && (
                <Section label="What it said to do instead">
                  {incident.diagnosis.service_advice.next_step}
                </Section>
              )}
            </>
          )}

          {incident.attempted_actions.length > 0 && (
            <Section label="Tried and did not work">
              <ul className="mt-1 space-y-1">
                {incident.attempted_actions.map((action) => (
                  <li key={action} className="flex items-center gap-2">
                    <span aria-hidden className="text-critical text-[11px]">
                      ✕
                    </span>
                    <span className="font-mono text-[11px] text-ink-2">{action}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {execution && (
            <Section label="What ran">
              <code className="mt-1 block overflow-x-auto rounded bg-sunken p-2.5 font-mono text-[11px] text-ink-2">
                {renderArgv(execution.argv)}
              </code>
              {verification && (
                <div className="mt-2 flex items-center gap-2">
                  <StatusDot
                    tone={
                      verification.outcome === "passed"
                        ? "good"
                        : verification.outcome === "failed"
                          ? "critical"
                          : "warning"
                    }
                    label={
                      verification.outcome === "passed"
                        ? "Verified fixed"
                        : verification.outcome === "failed"
                          ? "Did not fix it"
                          : "Could not tell"
                    }
                  />
                  <span className="text-[11px] text-muted">
                    after {verification.attempts} check
                    {verification.attempts === 1 ? "" : "s"}
                  </span>
                </div>
              )}
            </Section>
          )}

          {incident.symptoms.length > 0 && (
            <Section label="Evidence it was based on">
              <div className="mt-1 flex flex-wrap gap-1.5">
                {incident.symptoms.map((symptom) => (
                  <span
                    key={symptom.code}
                    className="rounded border border-hairline bg-sunken px-1.5 py-0.5 font-mono text-[10px] text-ink-2"
                  >
                    {symptom.code}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {incident.notes.length > 0 && (
            <ul className="space-y-1 text-[11px] text-muted">
              {incident.notes.map((note, index) => (
                <li key={index}>— {note}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </span>
      <div className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
      <span className="text-muted">
        <Icon name="history" size={36} />
      </span>
      <div>
        <p className="text-[15px] font-medium text-ink">Nothing has happened yet</p>
        <p className="mt-1 max-w-md text-[13px] leading-relaxed text-muted">
          When Warden notices something, the whole story ends up here — what it saw, what it
          concluded, what you approved, and whether it actually worked. Including the times it
          did not.
        </p>
      </div>
    </div>
  );
}
