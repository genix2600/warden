import type { Incident, Observation, OutputLine } from "../types";
import { renderArgv, since, stateLabel, stateTone } from "../lib/format";
import { ProposalCard } from "./ProposalCard";
import { Pill, StatusDot } from "./StatusDot";

interface Props {
  incident: Incident | null;
  monitoring: boolean;
  output: OutputLine[];
  observationsById: (id: string) => Observation | undefined;
  onInspect: (observation: Observation) => void;
  onApprove: (id: string) => Promise<void>;
  onDecline: (id: string) => Promise<void>;
  busy: boolean;
  elevated: boolean;
}

const STEPS = ["diagnosing", "awaiting_approval", "executing", "verifying"] as const;

export function IncidentStage({
  incident,
  monitoring,
  output,
  observationsById,
  onInspect,
  onApprove,
  onDecline,
  busy,
  elevated,
}: Props) {
  if (!incident) return <Idle monitoring={monitoring} />;

  const diagnosis = incident.diagnosis;
  const execution = incident.execution;
  const verification = execution?.verification;
  const advice = diagnosis?.service_advice;

  return (
    <div className="scroll-y flex h-full flex-col gap-4 pr-1">
      <header>
        <div className="flex flex-wrap items-center gap-2">
          <StatusDot tone={stateTone(incident.state)} label={stateLabel(incident.state)} />
          <span className="text-[11px] text-muted">opened {since(incident.opened_at)}</span>
          {incident.attempted_actions.length > 0 && (
            <Pill tone="warning">
              attempt {incident.attempted_actions.length + 1}
            </Pill>
          )}
        </div>
        <h1 className="mt-1.5 text-xl font-semibold text-ink">{incident.title}</h1>
        {!incident.closed_at && <Rail state={incident.state} />}
      </header>

      {!diagnosis && (
        <p className="pulse text-sm text-ink-2">
          Reading the machine and working out what this is…
        </p>
      )}

      {diagnosis && (
        <>
          <section className="rounded-xl border border-hairline bg-surface p-4">
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                What Warden concluded
              </h2>
              <Pill tone="idle">
                {diagnosis.reasoner.mode === "llm"
                  ? `local model · ${diagnosis.reasoner.model ?? "?"}`
                  : "rules engine"}
              </Pill>
            </div>
            <p className="text-[15px] leading-relaxed text-ink">{diagnosis.summary}</p>
            {diagnosis.reasoner.fallback_reason && (
              <p className="mt-2 text-[11px] leading-relaxed text-muted">
                The local model was not used: {diagnosis.reasoner.fallback_reason}. The
                deterministic rules engine answered instead — it reaches the same
                conclusions, it just writes shorter explanations.
              </p>
            )}
          </section>

          {diagnosis.reasoner.guardrail_rejections.length > 0 && (
            <section className="rounded-xl border border-hairline bg-surface p-4">
              <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                What Warden refused to do
              </h2>
              <ul className="space-y-1.5">
                {diagnosis.reasoner.guardrail_rejections.map((reason, index) => (
                  <li key={index} className="flex gap-2 text-[12px] leading-relaxed text-ink-2">
                    <span aria-hidden className="text-serious">
                      ▲
                    </span>
                    {reason}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {diagnosis.ranked_hypotheses.length > 0 && (
            <section>
              <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
                Ranked explanations
              </h2>
              <ol className="space-y-2">
                {diagnosis.ranked_hypotheses.map((hypothesis, index) => (
                  <li
                    key={index}
                    className="rounded-lg border border-hairline bg-surface p-3"
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-mono text-xs text-series-1 tabular-nums">
                        {(hypothesis.likelihood * 100).toFixed(0)}%
                      </span>
                      <span className="flex-1 text-[14px] font-medium text-ink">
                        {hypothesis.cause}
                      </span>
                      <Pill tone={hypothesis.domain === "hardware" ? "serious" : "idle"}>
                        {hypothesis.domain}
                      </Pill>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
                      {hypothesis.reasoning}
                    </p>
                    <Citations
                      label="supports"
                      ids={hypothesis.supporting}
                      lookup={observationsById}
                      onInspect={onInspect}
                    />
                    <Citations
                      label="argues against"
                      ids={hypothesis.contradicting}
                      lookup={observationsById}
                      onInspect={onInspect}
                    />
                  </li>
                ))}
              </ol>
            </section>
          )}

          {incident.state === "awaiting_approval" && diagnosis.proposal && (
            <ProposalCard
              proposal={diagnosis.proposal}
              busy={busy}
              onApprove={() => onApprove(incident.id)}
              onDecline={() => onDecline(incident.id)}
              elevated={elevated}
            />
          )}

          {advice && (
            <section className="rounded-xl border border-serious/40 bg-surface p-4">
              <div className="mb-2 flex items-center gap-2">
                <StatusDot tone="serious" />
                <h2 className="text-sm font-semibold text-ink">
                  {advice.who === "user"
                    ? "This one needs you, not a command"
                    : "This one needs a technician"}
                </h2>
              </div>
              <p className="text-[13px] leading-relaxed text-ink-2">{advice.reason}</p>
              <div className="mt-3 rounded-lg bg-sunken p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  {advice.who === "user" ? "What to do" : "What to tell them"}
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-ink">{advice.next_step}</p>
              </div>
              {advice.interim_mitigation && (
                <p className="mt-2 text-[12px] leading-relaxed text-ink-2">
                  <span className="text-muted">Meanwhile: </span>
                  {advice.interim_mitigation}
                </p>
              )}
            </section>
          )}
        </>
      )}

      {execution && (
        <section className="rounded-xl border border-hairline bg-surface p-4">
          <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
            What ran
          </h2>
          <code className="block overflow-x-auto rounded bg-sunken p-2.5 font-mono text-xs text-ink-2">
            <span className="text-muted">&gt; </span>
            {renderArgv(execution.argv)}
          </code>
          {output.length > 0 && (
            <pre className="scroll-y mt-2 max-h-44 rounded bg-sunken p-2.5 font-mono text-[11px] leading-relaxed">
              {output.map((line) => (
                <div
                  key={line.seq}
                  className={line.stream === "stderr" ? "text-critical" : "text-ink-2"}
                >
                  {line.text}
                </div>
              ))}
            </pre>
          )}
          {execution.blocked_reason && (
            <p className="mt-2 rounded border border-critical/40 bg-critical/10 p-2.5 text-[12px] text-critical">
              Refused before running: {execution.blocked_reason}
            </p>
          )}

          {verification && (
            <div className="mt-3 rounded-lg border border-hairline bg-sunken p-3">
              <div className="flex items-center gap-2">
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
                <span className="ml-auto text-[10px] text-muted">
                  {verification.attempts} check{verification.attempts === 1 ? "" : "s"}
                </span>
              </div>
              <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
                {verification.detail}
              </p>
            </div>
          )}
        </section>
      )}

      {incident.notes.length > 0 && (
        <ul className="space-y-1 text-[12px] text-muted">
          {incident.notes.map((note, index) => (
            <li key={index}>— {note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Citations({
  label,
  ids,
  lookup,
  onInspect,
}: {
  label: string;
  ids: string[];
  lookup: (id: string) => Observation | undefined;
  onInspect: (observation: Observation) => void;
}) {
  const found = ids.map(lookup).filter((o): o is Observation => Boolean(o));
  if (found.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      {found.map((observation) => (
        <button
          key={observation.id}
          type="button"
          onClick={() => onInspect(observation)}
          className="rounded border border-hairline bg-sunken px-1.5 py-0.5 font-mono text-[10px] text-ink-2 transition-colors hover:border-series-1 hover:text-ink"
        >
          {observation.source}
        </button>
      ))}
    </div>
  );
}

function Rail({ state }: { state: string }) {
  const current = STEPS.indexOf(state as (typeof STEPS)[number]);
  return (
    <ol className="mt-3 flex items-center gap-1.5">
      {STEPS.map((step, index) => {
        const done = current > index;
        const active = current === index;
        return (
          <li key={step} className="flex flex-1 items-center gap-1.5">
            <span
              className={`h-1 flex-1 rounded-full ${
                done ? "bg-series-1" : active ? "bg-series-1 pulse" : "bg-grid"
              }`}
            />
            <span
              className={`text-[10px] whitespace-nowrap ${active ? "text-ink" : "text-muted"}`}
            >
              {stateLabel(step)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Idle({ monitoring }: { monitoring: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div
        className={`grid size-14 place-items-center rounded-full border border-hairline ${monitoring ? "pulse" : ""}`}
      >
        <span aria-hidden className="text-2xl text-good">
          ✓
        </span>
      </div>
      <div>
        <p className="text-base font-medium text-ink">
          {monitoring ? "Watching. Nothing wrong." : "Not monitoring."}
        </p>
        <p className="mt-1 max-w-sm text-[13px] leading-relaxed text-muted">
          Warden stays quiet until it has something specific to show you, backed by a
          reading you can check. No score, no counter of invented problems.
        </p>
      </div>
    </div>
  );
}
