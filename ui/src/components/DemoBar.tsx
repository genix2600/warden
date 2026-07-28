import { useEffect, useState } from "react";
import { api } from "../lib/api";

/**
 * Fault injection, kept visibly separate from the agent.
 *
 * These buttons break the machine for real -- a real disconnection, a real
 * all-core load. Nothing here writes telemetry, and the agent has no access to
 * this module. It is fenced off and labelled because a demonstration that
 * secretly feeds the interface is worth nothing, and because someone reading
 * this repository should be able to see at a glance that the observations are
 * never synthesised.
 */
export function DemoBar() {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [load, setLoad] = useState({ active: false, remaining: 0 });

  useEffect(() => {
    const poll = window.setInterval(async () => {
      try {
        const status = await fetch("/api/demo/status").then((r) => r.json());
        setLoad({ active: status.load_active, remaining: status.load_remaining_s });
      } catch {
        /* backend restarting */
      }
    }, 2000);
    return () => window.clearInterval(poll);
  }, []);

  const run = async (name: string, call: () => Promise<{ detail: string }>) => {
    setBusy(name);
    try {
      setMessage((await call()).detail);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-hairline bg-sunken px-4 py-2">
      <span className="text-[10px] font-bold uppercase tracking-wider text-serious">
        Fault injection
      </span>
      <span className="text-[11px] text-muted">
        breaks this machine for real, so the diagnosis is real
      </span>

      <div className="ml-auto flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void run("wifi", api.dropWifi)}
          className="rounded border border-hairline px-2.5 py-1 text-[11px] text-ink-2 hover:bg-raised hover:text-ink disabled:opacity-50"
        >
          {busy === "wifi" ? "dropping…" : "Drop wireless"}
        </button>

        {load.active ? (
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void run("stop", api.stopLoad)}
            className="rounded border border-warning/50 px-2.5 py-1 text-[11px] text-warning hover:bg-raised disabled:opacity-50"
          >
            Stop load ({load.remaining.toFixed(0)}s left)
          </button>
        ) : (
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void run("cpu", () => api.loadCpu(150))}
            className="rounded border border-hairline px-2.5 py-1 text-[11px] text-ink-2 hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            {busy === "cpu" ? "starting…" : "Load all cores (150s)"}
          </button>
        )}
      </div>

      {message && (
        <p className="w-full text-[11px] leading-snug text-muted">{message}</p>
      )}
    </div>
  );
}
