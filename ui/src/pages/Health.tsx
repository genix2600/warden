import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { briefValue, domainLabel, domainTone, toneClass } from "../lib/format";
import type { DomainHealth, Observation } from "../types";
import { Icon } from "../components/Icon";
import { StatusDot } from "../components/StatusDot";
import { PageHeader } from "../components/PageHeader";

/**
 * Every part of the machine, in the words a person would use for it.
 *
 * The ordering is deliberate: anything wrong floats to the top, and the long
 * tail of "fine" sits below. A dashboard that keeps a broken printer in
 * alphabetical position between Bluetooth and Search is making the user do the
 * scanning that the software was supposed to do for them.
 */
export function Health({
  onInspect,
  tick,
  onChecked,
}: {
  onInspect: (observation: Observation) => void;
  tick: number;
  /** Called after a check starts something, so the shell can show the incident. */
  onChecked: (started: number) => void;
}) {
  const [domains, setDomains] = useState<DomainHealth[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const check = useCallback(
    async (domainId?: string) => {
      setChecking(domainId ?? "__all__");
      setNote(null);
      try {
        const result = await api.check(domainId);
        setNote(result.detail);
        if (result.started.length > 0) onChecked(result.started.length);
      } catch (problem) {
        setNote(problem instanceof Error ? problem.message : String(problem));
      } finally {
        setChecking(null);
      }
    },
    [onChecked],
  );

  useEffect(() => {
    let alive = true;
    api
      .domains()
      .then((next) => alive && setDomains(next))
      .catch((problem: unknown) => {
        if (alive) setError(problem instanceof Error ? problem.message : String(problem));
      });
    return () => {
      alive = false;
    };
    // Re-fetch as the agent ticks, so this page is live rather than a snapshot.
  }, [tick]);

  const rank: Record<string, number> = {
    problem: 0,
    attention: 1,
    note: 2,
    unknown: 3,
    ok: 4,
  };
  const sorted = domains ? [...domains].sort((a, b) => rank[a.state]! - rank[b.state]!) : [];
  const wrong = sorted.filter((d) => d.state === "problem" || d.state === "attention");
  const fine = sorted.filter((d) => d.state === "ok").length;

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Health"
        subtitle={
          domains === null
            ? "Checking every part of the machine…"
            : wrong.length === 0
              ? `All ${domains.length} areas checked. ${fine} working normally, nothing needs you.`
              : `${wrong.length} of ${domains.length} areas need attention.`
        }
        actions={
          <button
            type="button"
            onClick={() => void check()}
            disabled={checking !== null}
            className="rounded-lg bg-series-1 px-3.5 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {checking === "__all__" ? "Looking…" : "Check everything"}
          </button>
        }
      />

      {/* Warden watches on its own but does not interrupt on its own, so the
          findings above sit here until someone asks about them. */}
      {note && <p className="mb-3 text-[12px] text-ink-2">{note}</p>}

      {error && <p className="text-[13px] text-critical">{error}</p>}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sorted.map((domain) => (
          <DomainCard
            key={domain.id}
            domain={domain}
            onInspect={onInspect}
            onCheck={() => void check(domain.id)}
            checking={checking === domain.id}
          />
        ))}
      </div>

      {domains !== null && (
        <p className="mt-5 max-w-2xl text-[12px] leading-relaxed text-muted">
          Each area is checked by reading the machine directly, not by asking Windows for a
          summary. An area shows <span className="text-ink-2">Can&apos;t tell</span> when the
          reading failed — Warden will not report something as healthy because it could not
          look at it.
        </p>
      )}
    </div>
  );
}

function DomainCard({
  domain,
  onInspect,
  onCheck,
  checking,
}: {
  domain: DomainHealth;
  onInspect: (observation: Observation) => void;
  onCheck: () => void;
  checking: boolean;
}) {
  const tone = domainTone(domain.state);
  const attention = domain.state === "problem" || domain.state === "attention";
  const highlights = Object.entries(domain.highlights);

  return (
    <section
      className={`rounded-xl border bg-surface p-4 transition-colors ${
        attention ? "border-critical/40" : "border-hairline"
      }`}
    >
      <header className="flex items-start gap-3">
        <span className={`mt-0.5 ${attention ? toneClass(tone) : "text-muted"}`}>
          <Icon name={domain.icon} size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-semibold text-ink">{domain.label}</h3>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">{domain.blurb}</p>
        </div>
        <StatusDot tone={tone} />
      </header>

      <p
        className={`mt-3 text-[13px] leading-relaxed ${attention ? "text-ink" : "text-ink-2"}`}
      >
        {domain.headline}
      </p>

      <div className="mt-3 flex items-center gap-2">
        <span className={`text-[11px] font-medium ${toneClass(tone)}`}>
          {domainLabel(domain.state)}
        </span>
        {domain.active_symptoms.length > 0 && (
          <span className="text-[11px] text-muted">
            · {domain.active_symptoms.length} finding
            {domain.active_symptoms.length === 1 ? "" : "s"}
          </span>
        )}
        <button
          type="button"
          onClick={onCheck}
          disabled={checking}
          className="ml-auto rounded-lg border border-hairline px-2.5 py-1 text-[11px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
        >
          {checking ? "Looking…" : "Look into this"}
        </button>
      </div>

      {highlights.length > 0 && (
        <dl className="mt-3 space-y-1 border-t border-hairline pt-2.5">
          {highlights.slice(0, 3).map(([source, observation]) => {
            const brief = briefValue(observation.value);
            return (
              <div key={source} className="flex items-baseline gap-2">
                <dt className="truncate font-mono text-[10px] text-muted">
                  {source.split(".").slice(-2).join(".")}
                </dt>
                <dd className="ml-auto flex items-center gap-1.5">
                  <span className="truncate font-mono text-[11px] text-ink-2">
                    {brief ?? "—"}
                    {observation.unit && brief !== null ? ` ${observation.unit}` : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => onInspect(observation)}
                    title="How was this read?"
                    className="text-muted transition-colors hover:text-series-1"
                  >
                    <Icon name="search" size={12} />
                  </button>
                </dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}
