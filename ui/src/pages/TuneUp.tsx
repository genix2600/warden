import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { checkLabel, checkTone, toneClass } from "../lib/format";
import type { AuditReport, CheckResult, CheckStatus } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusDot } from "../components/StatusDot";
import { BY_DOMAIN } from "../lib/domains";

/**
 * Settings that are wrong but have not broken anything.
 *
 * The rest of Warden reacts to faults. This page is the standing review: things
 * set once at the factory or by an installer, never looked at since, each with a
 * measurable cost. Nothing here is failing, which is exactly why nobody has
 * found it.
 *
 * Two rules govern what may appear. Every finding names a quantity Warden can
 * read before and after -- enforced in the contracts, not here -- and nothing on
 * this page ever reaches out to interrupt. No banner, no sidebar badge, no
 * count on a surface the user did not navigate to. A tool that nags about
 * settings is the thing this feature was written not to be.
 */
export function TuneUp() {
  const [report, setReport] = useState<AuditReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.audit());
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, []);

  // On open, and on request. Deliberately not on a timer.
  useEffect(() => {
    void run();
  }, [run]);

  const results = report?.results ?? [];
  const rank: Record<string, number> = {
    suboptimal: 0,
    intent_dependent: 1,
    could_not_read: 2,
    not_applicable: 3,
    optimal: 4,
  };
  const sorted = [...results].sort((a, b) => rank[a.status]! - rank[b.status]!);
  const worth = results.filter((r) => r.status === "suboptimal");
  const depends = results.filter((r) => r.status === "intent_dependent");
  const settled = results.filter((r) => r.status === "optimal");

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Tune-up"
        subtitle={summary(report, worth.length, depends.length, settled.length)}
        actions={
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy}
            className="rounded-lg border border-hairline px-3 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check again"}
          </button>
        }
      />

      {error && <p className="mb-4 text-[13px] text-critical">{error}</p>}

      {report && results.length === 0 && (
        <p className="py-16 text-center text-[13px] text-muted">
          No checks ran. That is a bug, not a clean bill of health.
        </p>
      )}

      <div className="space-y-2.5">
        {sorted.map((result) => (
          <Finding key={result.check_id} result={result} />
        ))}
      </div>

      {report && (
        <p className="mt-6 max-w-2xl border-t border-hairline pt-4 text-[12px] leading-relaxed text-muted">
          Warden only lists a setting when it can measure what changes. If it cannot tell
          you the number, it does not tell you to change it — which is why there is no
          registry cleaning here, and no button promising a percentage.
        </p>
      )}
    </div>
  );
}

function summary(
  report: AuditReport | null,
  worth: number,
  depends: number,
  settled: number,
): string {
  if (report === null) return "Looking at settings that are easy to get wrong…";
  const total = report.results.length;
  if (worth === 0 && depends === 0) {
    return `Warden checked ${total} settings. All of them are already right.`;
  }
  const parts = [`Warden checked ${total} settings`, `${settled} are already right`];
  if (worth > 0) parts.push(`${worth} ${worth === 1 ? "is" : "are"} worth changing`);
  if (depends > 0) {
    parts.push(`${depends} ${depends === 1 ? "depends" : "depend"} on what you want`);
  }
  return `${parts.join(", ")}.`;
}

function Finding({ result }: { result: CheckResult }) {
  const tone = checkTone(result.status);
  const attention = result.status === "suboptimal";
  const domain = BY_DOMAIN[result.domain_id];

  return (
    <article
      className={`rounded-xl border bg-surface p-4 ${
        attention ? "border-warning/40" : "border-hairline"
      }`}
    >
      <header className="flex items-start gap-3">
        <span className={`mt-0.5 ${attention ? toneClass(tone) : "text-muted"}`}>
          <Icon name={domain?.icon ?? "shield"} size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-[14px] font-semibold text-ink">{result.title}</h3>
            <span className="text-[11px] text-muted">{domain?.label ?? result.domain_id}</span>
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{result.detail}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <StatusDot tone={tone} />
          <span className={`text-[11px] font-medium ${toneClass(tone)}`}>
            {checkLabel(result.status)}
          </span>
        </div>
      </header>

      {(result.observed !== null || result.expected !== null) && (
        <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-1.5 border-t border-hairline pt-2.5">
          {result.observed !== null && (
            <Pair label="Now" value={String(result.observed)} />
          )}
          {result.expected !== null && (
            <Pair label="Would become" value={String(result.expected)} accent />
          )}
        </dl>
      )}

      {attention && (
        <p className="mt-3 rounded-lg bg-sunken px-3 py-2 text-[11px] leading-relaxed text-muted">
          Warden is not offering to change this yet. It reports what it measured; applying
          settings from this page comes with the same approval card, evidence and
          verification as everything else, and is not finished.
        </p>
      )}
    </article>
  );
}

function Pair({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-[10px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`font-mono text-[12px] ${accent ? "text-good" : "text-ink-2"}`}>{value}</dd>
    </div>
  );
}

export type { CheckStatus };
