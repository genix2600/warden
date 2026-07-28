import type { Incident, Observation } from "../types";
import type { LogLine, WardenState } from "../lib/useWarden";
import { AgentLog } from "../components/AgentLog";
import { Icon } from "../components/Icon";
import { IncidentStage } from "../components/IncidentStage";
import { TelemetryPanel } from "../components/TelemetryPanel";

interface Props {
  state: WardenState;
  focus: Incident | null;
  log: LogLine[];
  onInspect: (observation: Observation) => void;
  onApprove: (id: string) => Promise<void>;
  onDecline: (id: string) => Promise<void>;
  onSeeHealth: () => void;
  busy: boolean;
}

/**
 * What is happening right now.
 *
 * The only page that demands attention. Everything else in the app is available
 * on request; this one is what a person sees when they open Warden because
 * something is wrong, so it leads with the answer rather than with telemetry.
 */
export function Overview({
  state,
  focus,
  log,
  onInspect,
  onApprove,
  onDecline,
  onSeeHealth,
  busy,
}: Props) {
  const monitoring = state.snapshot?.monitoring ?? false;
  const waiting = focus?.state === "awaiting_approval";

  return (
    <div className="flex h-full flex-col">
      <Banner
        monitoring={monitoring}
        waiting={waiting}
        incident={focus}
        onSeeHealth={onSeeHealth}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)_276px] gap-4 px-4 pb-4">
        <TelemetryPanel
          telemetry={state.telemetry}
          series={state.series}
          collectors={state.snapshot?.collectors ?? []}
          onInspect={onInspect}
        />
        <IncidentStage
          incident={focus}
          monitoring={monitoring}
          output={focus ? (state.output[focus.id] ?? []) : []}
          observationsById={(id) =>
            Object.values(state.telemetry).find((observation) => observation.id === id)
          }
          onInspect={onInspect}
          onApprove={onApprove}
          onDecline={onDecline}
          busy={busy}
        />
        <AgentLog lines={log} />
      </div>
    </div>
  );
}

/**
 * A single sentence at the top saying whether the user needs to do anything.
 *
 * Deliberately the largest text on the page. The most common state is "nothing
 * is wrong", and saying that plainly -- rather than showing a wall of green
 * dials that the user has to interpret -- is the difference between a tool that
 * reassures and one that adds to the anxiety it was meant to remove.
 */
function Banner({
  monitoring,
  waiting,
  incident,
  onSeeHealth,
}: {
  monitoring: boolean;
  waiting: boolean;
  incident: Incident | null;
  onSeeHealth: () => void;
}) {
  const open = incident && !["resolved", "unresolved", "needs_service", "declined"].includes(
    incident.state,
  );

  let tone = "text-good";
  let icon = "check";
  let headline = "Everything looks fine";
  let detail = monitoring
    ? "Warden is watching. It will only interrupt you if it finds something specific."
    : "Warden is not currently watching this machine.";

  if (waiting) {
    tone = "text-warning";
    icon = "shield";
    headline = "Warden needs your permission";
    detail = "It found something, worked out a fix, and is waiting for you to approve it.";
  } else if (open) {
    tone = "text-series-1";
    icon = "gauge";
    headline = "Looking into something";
    detail = incident?.title ?? "";
  } else if (incident?.state === "needs_service") {
    tone = "text-serious";
    icon = "shield";
    headline = "This one needs a person, not a command";
    detail = incident.title;
  }

  return (
    <div className="flex items-center gap-3 px-6 pb-4 pt-5">
      <span className={tone}>
        <Icon name={icon} size={26} />
      </span>
      <div className="min-w-0 flex-1">
        <h1 className="text-[19px] font-semibold tracking-tight text-ink">{headline}</h1>
        <p className="mt-0.5 truncate text-[13px] text-ink-2">{detail}</p>
      </div>
      <button
        type="button"
        onClick={onSeeHealth}
        className="shrink-0 rounded-lg border border-hairline px-3 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-raised hover:text-ink"
      >
        See every area
      </button>
    </div>
  );
}
