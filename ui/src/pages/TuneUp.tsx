import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { checkLabel, checkTone, renderArgv, toneClass } from "../lib/format";
import type {
  AuditApplied,
  AuditReport,
  CheckResult,
  CheckStatus,
  Recommendation,
} from "../types";
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
 * Three rules govern what appears. Every finding names a quantity Warden can
 * read before and after, enforced in the contracts rather than here. Every fix
 * has to be undoable, which is why the obvious one (deleting temporary files) is
 * absent. And nothing on this page ever reaches out to interrupt: no banner, no
 * sidebar badge, no count on a surface the user did not navigate to.
 */
export function TuneUp() {
  const [report, setReport] = useState<AuditReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, AuditApplied>>({});

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

  const applyOne = useCallback(
    async (checkId: string, revert: boolean) => {
      setWorking(checkId);
      try {
        const result = await api.applyTuneup(checkId, revert);
        setOutcomes((current) => ({ ...current, [checkId]: result }));
      } catch (problem) {
        setOutcomes((current) => ({
          ...current,
          [checkId]: {
            ok: false,
            detail: problem instanceof Error ? problem.message : String(problem),
            change: "",
            reverted: revert,
          },
        }));
      } finally {
        setWorking(null);
      }
    },
    [],
  );

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
  const byCheck: Record<string, Recommendation> = Object.fromEntries(
    (report?.recommendations ?? []).map((r) => [r.result.check_id, r]),
  );

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
          <Finding
            key={result.check_id}
            result={result}
            recommendation={byCheck[result.check_id]}
            onApply={(id, revert) => void applyOne(id, revert)}
            busy={working === result.check_id}
            outcome={outcomes[result.check_id]}
          />
        ))}
      </div>

      {report && (
        <p className="mt-6 max-w-2xl border-t border-hairline pt-4 text-[12px] leading-relaxed text-muted">
          Warden only lists a setting when it can measure what changes, and only
          offers to change one when it can put it back. That is why there is no
          registry cleaning here, no button promising a percentage, and no
          one-click delete of your temporary files.
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

function Finding({
  result,
  recommendation,
  onApply,
  busy,
  outcome,
}: {
  result: CheckResult;
  recommendation?: Recommendation;
  onApply: (checkId: string, revert: boolean) => void;
  busy: boolean;
  outcome?: AuditApplied;
}) {
  const tone = checkTone(result.status);
  const attention = result.status === "suboptimal";
  const domain = BY_DOMAIN[result.domain_id];
  const proposal = recommendation?.proposal ?? null;
  const choices = recommendation?.choices ?? [];

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
          {result.observed !== null && <Pair label="Now" value={String(result.observed)} />}
          {result.expected !== null && (
            <Pair label="Would become" value={String(result.expected)} accent />
          )}
        </dl>
      )}

      {/* A question with no correct answer. Both costs, and no recommendation,
          because Warden cannot know which one this person wants. */}
      {choices.length > 0 && (
        <div className="mt-3 grid gap-2 border-t border-hairline pt-3 sm:grid-cols-2">
          {choices.map((choice) => (
            <div key={choice.id} className="rounded-lg bg-sunken px-3 py-2.5">
              <h4 className="text-[12px] font-semibold text-ink">{choice.label}</h4>
              <p className="mt-0.5 text-[11px] leading-snug text-muted">{choice.cost}</p>
            </div>
          ))}
          <p className="text-[11px] leading-relaxed text-muted sm:col-span-2">
            Warden has no way to tell which of these you want, so it is not
            recommending either.
          </p>
        </div>
      )}

      {proposal && !outcome && (
        <div className="mt-3 border-t border-hairline pt-3">
          <p className="mb-2 text-[11px] leading-relaxed text-muted">
            Expected: {recommendation?.expected_improvement}
          </p>
          <code className="block overflow-x-auto rounded-lg bg-sunken p-2.5 font-mono text-[11px] leading-relaxed text-ink-2">
            <span className="text-muted">&gt; </span>
            {renderArgv(proposal.rendered_argv)}
          </code>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => onApply(result.check_id, false)}
              className="rounded-lg bg-series-1 px-3.5 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Applying…" : "Apply this"}
            </button>
            {recommendation?.revert && (
              <span className="text-[11px] text-muted">{recommendation.revert.describe}</span>
            )}
          </div>
        </div>
      )}

      {outcome && (
        <div className="mt-3 rounded-lg border border-hairline bg-sunken p-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusDot tone={outcome.ok ? "good" : "critical"} />
            <span className="text-[12px] font-medium text-ink">{outcome.detail}</span>
            {outcome.ok && !outcome.reverted && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onApply(result.check_id, true)}
                className="ml-auto rounded-lg border border-hairline px-2.5 py-1 text-[11px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
              >
                Undo this
              </button>
            )}
          </div>
          {/* Shown whichever way it went. An audit that always reports an
              improvement is indistinguishable from the tools this one exists
              to replace. */}
          {outcome.change && (
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">{outcome.change}</p>
          )}
        </div>
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
