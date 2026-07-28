import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { DoctorReport } from "../types";
import { StatusDot } from "./StatusDot";

/**
 * Pre-flight, meant to be run in front of an audience.
 *
 * Every check here corresponds to something that has actually gone wrong: a
 * cold PowerShell host, a model that was never pulled, a machine with no saved
 * wireless profile so there is nothing to reconnect to. Blocking checks are the
 * ones without which a live run is impossible; the rest degrade honestly.
 */
export function DoctorPanel({ onClose }: { onClose: () => void }) {
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .doctor()
      .then(setReport)
      .catch((problem: unknown) =>
        setError(problem instanceof Error ? problem.message : String(problem)),
      );
  }, []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6" onClick={onClose}>
      <section
        className="rise w-full max-w-lg rounded-xl border border-hairline bg-surface"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="Readiness"
      >
        <header className="flex items-center justify-between border-b border-hairline px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Readiness</h2>
          {report && (
            <StatusDot
              tone={report.ready ? "good" : "critical"}
              label={report.ready ? "ready to demonstrate" : "not ready"}
            />
          )}
        </header>

        <div className="space-y-2 p-4">
          {error && <p className="text-[12px] text-critical">{error}</p>}
          {!report && !error && <p className="pulse text-[12px] text-muted">checking…</p>}
          {report?.checks.map((check) => (
            <div
              key={check.name}
              className="flex gap-3 rounded-lg border border-hairline bg-sunken p-3"
            >
              <StatusDot tone={check.ok ? "good" : check.blocking ? "critical" : "warning"} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-[13px] font-medium text-ink">{check.name}</span>
                  {!check.blocking && (
                    <span className="text-[10px] uppercase tracking-wide text-muted">
                      optional
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{check.detail}</p>
              </div>
            </div>
          ))}
        </div>

        <footer className="border-t border-hairline px-4 py-3 text-right">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-hairline px-3 py-1.5 text-[12px] text-ink-2 hover:bg-raised hover:text-ink"
          >
            Close
          </button>
        </footer>
      </section>
    </div>
  );
}
