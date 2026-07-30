import { useEffect } from "react";
import type { Observation } from "../types";
import { clockTime } from "../lib/format";

/**
 * The "how do you know that" panel.
 *
 * Every reading Warden shows carries the exact command that produced it, how
 * long it took, and how much the collector trusts it. This drawer is where that
 * provenance becomes visible, and it is the concrete answer to the question a
 * chatbot cannot answer: not "what do you think is wrong" but "what did you
 * actually read, and can I read it myself".
 */
export function EvidenceDrawer({
  observation,
  onClose,
}: {
  observation: Observation | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!observation) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="rise flex h-full w-[520px] max-w-full flex-col border-l border-hairline bg-surface"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label="Evidence detail"
      >
        <header className="flex items-start justify-between border-b border-hairline p-4">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-muted">Reading</p>
            <h2 className="font-mono text-sm text-ink">{observation.source}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-sm text-muted hover:bg-raised hover:text-ink"
          >
            Close
          </button>
        </header>

        <div className="scroll-y flex-1 space-y-4 p-4">
          <Field label="How it was read">
            <code className="block rounded bg-sunken p-2.5 font-mono text-xs leading-relaxed text-ink-2 select-all">
              {observation.provenance.probe}
            </code>
            <p className="mt-1.5 text-[11px] text-muted">
              You can run this yourself and get the same answer.
            </p>
          </Field>

          <div className="grid grid-cols-3 gap-2">
            <Meta label="Mechanism" value={observation.provenance.mechanism} />
            <Meta label="Took" value={`${observation.provenance.elapsed_ms} ms`} />
            <Meta
              label="Confidence"
              value={`${(observation.confidence * 100).toFixed(0)}%`}
            />
          </div>

          {observation.confidence < 1 && (
            <p className="rounded border border-hairline bg-sunken p-2.5 text-[11px] leading-relaxed text-ink-2">
              This source is not fully authoritative. It is either derived rather than
              measured directly, or parsed from output that varies by system language.
              Warden weights it accordingly instead of treating it as certain.
            </p>
          )}

          <Field label={`Value${observation.unit ? ` (${observation.unit})` : ""}`}>
            <pre className="scroll-y max-h-80 rounded bg-sunken p-2.5 font-mono text-xs leading-relaxed text-ink-2">
              {JSON.stringify(observation.value, null, 2)}
            </pre>
          </Field>

          <Field label="Captured">
            <span className="font-mono text-xs text-ink-2">
              {clockTime(observation.captured_at)}
            </span>
          </Field>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </h3>
      {children}
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-hairline bg-sunken p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 font-mono text-xs text-ink">{value}</div>
    </div>
  );
}
