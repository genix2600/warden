import type { AgentSnapshot } from "../types";
import { Logo } from "./Logo";
import { Pill, StatusDot } from "./StatusDot";

export function Header({
  snapshot,
  connected,
  desynced,
  onResync,
  onOpenDoctor,
}: {
  snapshot: AgentSnapshot | null;
  connected: boolean;
  desynced: boolean;
  onResync: () => void;
  onOpenDoctor: () => void;
}) {
  const replaying = snapshot?.source === "replay";
  const reasoner = snapshot?.reasoner;

  return (
    <header className="flex items-center gap-3 border-b border-hairline bg-surface px-5 py-2">
      <Logo size={17} />

      {/* Three states. Warming is not paused: both mean nothing is being
          watched yet, but only one of them means Warden is working on it, and
          labelling startup "Paused" told the user it was idle at the moment it
          was busiest. */}
      <StatusDot
        tone={
          !connected ? "critical" : snapshot?.monitoring ? "good" : snapshot?.warming ? "warning" : "idle"
        }
        label={
          !connected
            ? "Not connected"
            : snapshot?.monitoring
              ? "Watching this machine"
              : snapshot?.warming
                ? "Starting up"
                : "Paused"
        }
      />

      {/* A replayed session is labelled permanently and unmistakably. Recorded
          data presented as live would destroy the only thing this tool sells. */}
      {replaying && (
        <span className="rounded bg-warning px-2 py-0.5 text-[11px] font-bold text-plane">
          REPLAY — recorded session, not this machine
        </span>
      )}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {desynced && (
          <button
            type="button"
            onClick={onResync}
            className="rounded border border-warning/50 px-2 py-1 text-[11px] text-warning hover:bg-raised"
          >
            missed some events — resync
          </button>
        )}

        {reasoner && (
          <Pill tone={reasoner.available ? "good" : "idle"}>
            {reasoner.available ? reasoner.model : "rules engine"}
          </Pill>
        )}

        {snapshot?.elevated ? (
          <Pill tone="idle">administrator</Pill>
        ) : (
          <Pill tone="idle">standard user</Pill>
        )}

        <span className="font-mono text-[11px] text-muted tabular-nums">
          tick {snapshot?.tick ?? 0}
        </span>

        <button
          type="button"
          onClick={onOpenDoctor}
          className="rounded border border-hairline px-2 py-1 text-[11px] text-ink-2 hover:bg-raised hover:text-ink"
        >
          Readiness
        </button>

      </div>
    </header>
  );
}
