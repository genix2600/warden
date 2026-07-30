import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AgentSnapshot, DoctorReport } from "../types";
import { ElevateButton } from "../components/ElevateButton";
import { GetModelButton } from "../components/GetModelButton";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusDot } from "../components/StatusDot";

/**
 * Whether Warden is set up to do its job on this machine.
 *
 * Every check here corresponds to something that has actually gone wrong during
 * development: a cold PowerShell host, a model that was never pulled, a machine
 * with no saved wireless profile so there is nothing to reconnect to. The
 * optional ones are the point -- they degrade honestly rather than failing, and
 * the page says which capability is lost rather than just showing a warning.
 */
export function Readiness({ snapshot }: { snapshot: AgentSnapshot | null }) {
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.doctor());
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const blocking = report?.checks.filter((c) => c.blocking) ?? [];
  const optional = report?.checks.filter((c) => !c.blocking) ?? [];

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Readiness"
        subtitle={
          report
            ? report.ready
              ? "Everything Warden needs in order to diagnose and fix things is working."
              : "Something essential is missing. Warden will still watch, but some fixes are unavailable."
            : "Checking…"
        }
        actions={
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={busy}
            className="rounded-lg border border-hairline px-3 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check again"}
          </button>
        }
      />

      {error && <p className="mb-4 text-[13px] text-critical">{error}</p>}

      {report && (
        <>
          <Group
            title="Essential"
            blurb="Without these, Warden cannot do its job on this machine."
            checks={blocking}
          />
          <Group
            title="Optional"
            blurb="Warden works without these. Each one that is missing costs a specific capability, named below."
            checks={optional}
          />
        </>
      )}

      {snapshot && (
        <section className="mt-2 rounded-xl border border-hairline bg-surface p-4">
          <h2 className="mb-2 text-[13px] font-semibold text-ink">This machine</h2>
          <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
            {Object.entries(snapshot.host).map(([key, value]) => (
              <div key={key} className="flex items-baseline gap-2">
                <dt className="text-[11px] capitalize text-muted">{key}</dt>
                <dd className="ml-auto truncate font-mono text-[11px] text-ink-2">{value}</dd>
              </div>
            ))}
            <div className="flex items-baseline gap-2">
              <dt className="text-[11px] text-muted">Collectors</dt>
              <dd className="ml-auto font-mono text-[11px] text-ink-2">
                {snapshot.collectors.filter((c) => c.healthy).length} of{" "}
                {snapshot.collectors.length} reporting
              </dd>
            </div>
            {snapshot.session_path && (
              <div className="flex items-baseline gap-2 sm:col-span-2">
                <dt className="text-[11px] text-muted">Session recorded to</dt>
                <dd className="ml-auto truncate font-mono text-[11px] text-ink-2">
                  {snapshot.session_path}
                </dd>
              </div>
            )}
          </dl>
        </section>
      )}
    </div>
  );
}

function Group({
  title,
  blurb,
  checks,
}: {
  title: string;
  blurb: string;
  checks: DoctorReport["checks"];
}) {
  if (checks.length === 0) return null;
  return (
    <section className="mb-5">
      <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
      <p className="mb-2.5 text-[12px] text-muted">{blurb}</p>
      <div className="space-y-2">
        {checks.map((check) => (
          <div
            key={check.name}
            className="flex gap-3 rounded-lg border border-hairline bg-surface p-3"
          >
            <span className="mt-0.5">
              <StatusDot
                tone={check.ok ? "good" : check.blocking ? "critical" : "warning"}
              />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-[13px] font-medium text-ink">{check.name}</h3>
              <p className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{check.detail}</p>
              {/* The one check with a one-click remedy. Offered here rather than
                  demanded at launch, so Warden still runs on a machine where
                  the user is not an administrator. */}
              {!check.ok && check.name === "Administrator" && <ElevateButton />}
              {/* The standard build ships without weights to keep the download
                  small; this is where they are fetched, on request. */}
              {!check.ok && check.name === "Local model" && <GetModelButton />}
            </div>
            {check.ok && (
              <span className="mt-0.5 shrink-0 text-good">
                <Icon name="check" size={15} />
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
