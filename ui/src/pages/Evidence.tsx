import { useMemo, useState } from "react";
import { briefValue, clockTime } from "../lib/format";
import type { Observation } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";

/**
 * Every reading Warden currently holds, and the command that produced each one.
 *
 * This page is the answer to "how do you know that", made browsable rather than
 * buried one incident at a time. Nothing here is a summary or a derived score --
 * each row is a value Warden read off the machine, with the command next to it,
 * so any claim it makes elsewhere can be traced back to something checkable.
 */
export function Evidence({
  telemetry,
  onInspect,
}: {
  telemetry: Record<string, Observation>;
  onInspect: (observation: Observation) => void;
}) {
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const all = Object.values(telemetry).sort((a, b) => a.source.localeCompare(b.source));
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter(
      (o) =>
        o.source.toLowerCase().includes(needle) ||
        o.provenance.probe.toLowerCase().includes(needle) ||
        JSON.stringify(o.value).toLowerCase().includes(needle),
    );
  }, [telemetry, query]);

  const groups = useMemo(() => {
    const map = new Map<string, Observation[]>();
    for (const observation of rows) {
      const prefix = observation.source.split(".")[0] ?? "other";
      map.set(prefix, [...(map.get(prefix) ?? []), observation]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [rows]);

  const total = Object.keys(telemetry).length;

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Readings"
        subtitle={`Everything Warden has read from this machine. ${total} live values, each with the exact command that produced it. You can run any of them yourself and get the same answer.`}
        actions={
          <div className="relative">
            <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted">
              <Icon name="search" size={14} />
            </span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter readings…"
              className="w-56 rounded-lg border border-hairline bg-sunken py-1.5 pl-8 pr-2.5 text-[12px] text-ink placeholder:text-muted focus:border-series-1 focus:outline-none"
            />
          </div>
        }
      />

      {total === 0 && (
        <p className="py-16 text-center text-[13px] text-muted">
          Waiting for the first readings to come in…
        </p>
      )}

      {total > 0 && rows.length === 0 && (
        <p className="py-16 text-center text-[13px] text-muted">
          Nothing matches “{query}”.
        </p>
      )}

      {groups.map(([prefix, observations]) => (
        <section key={prefix} className="mb-5">
          <h2 className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-muted">
            {prefix}
          </h2>
          <div className="overflow-hidden rounded-lg border border-hairline">
            <table className="w-full border-collapse text-left">
              <tbody>
                {observations.map((observation, index) => (
                  <tr
                    key={observation.id}
                    className={`${index > 0 ? "border-t border-hairline" : ""} bg-surface`}
                  >
                    <td className="w-56 px-3 py-2 align-top">
                      <div className="font-mono text-[11px] text-ink">{observation.source}</div>
                      <div className="text-[10px] text-muted">
                        {clockTime(observation.captured_at)} ·{" "}
                        {observation.provenance.elapsed_ms}ms
                      </div>
                    </td>
                    <td className="px-3 py-2 align-top">
                      <div className="font-mono text-[11px] text-ink-2">
                        {briefValue(observation.value) ??
                          JSON.stringify(observation.value).slice(0, 90)}
                        {observation.unit ? ` ${observation.unit}` : ""}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[10px] text-muted">
                        {observation.provenance.probe}
                      </div>
                    </td>
                    <td className="w-28 px-3 py-2 text-right align-top">
                      {observation.confidence < 1 && (
                        <span
                          className="mr-2 text-[10px] text-warning"
                          title="Derived or locale-dependent, so weighted lower than a direct measurement"
                        >
                          {(observation.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => onInspect(observation)}
                        className="rounded border border-hairline px-2 py-1 text-[10px] text-ink-2 transition-colors hover:border-series-1 hover:text-ink"
                      >
                        Show me
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
