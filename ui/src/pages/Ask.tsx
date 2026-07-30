import { useCallback, useState } from "react";
import { api } from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Icon } from "../components/Icon";

/**
 * Telling Warden what is wrong, in your own words.
 *
 * Every other way into this application starts with a detector. That is the
 * right default and it has a hard ceiling: a detector finds what it was written
 * to find, and the person sitting in front of a broken machine routinely knows
 * something no collector reads. It started after Tuesday's update. It only
 * happens on the external monitor. Sound works in one application and not
 * another. None of that is measurable and all of it is the diagnosis.
 *
 * What this is not is a chatbot. There is no conversation, no personality and
 * no small talk, because none of those help and the interface has spent every
 * other screen arguing that Warden does not pretend. A description opens a real
 * incident, goes through the same reasoner and the same guardrail, and comes
 * back as a proposal you approve on the Now page like any other. The answer to
 * "what should I type" is "what you would tell a person", and the answer to
 * "then what" is "the same thing that happens when Warden finds it itself".
 */
export function Ask({ onOpened }: { onOpened: () => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState<{ you: string; warden: string } | null>(null);

  const send = useCallback(async () => {
    const text = message.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const reply = await api.ask(text);
      setSaid({ you: text, warden: reply.reply });
      setMessage("");
      if (reply.incident_id) onOpened();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [message, onOpened]);

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Describe a problem"
        subtitle="Warden's detectors find what they were written to find. You know things they cannot read."
      />

      {error && <p className="mb-4 text-[13px] text-critical">{error}</p>}

      <div className="max-w-2xl">
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
          }}
          rows={4}
          placeholder="My laptop has no sound since the update on Tuesday. It works through headphones but not the speakers."
          className="w-full resize-y rounded-xl border border-hairline bg-sunken px-3.5 py-3 text-[14px] leading-relaxed text-ink outline-none placeholder:text-muted focus:border-series-1"
        />
        <div className="mt-2.5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void send()}
            disabled={busy || message.trim().length === 0}
            className="rounded-lg bg-series-1 px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Working it out…" : "Ask Warden"}
          </button>
          <span className="text-[12px] text-muted">
            Ctrl+Enter also sends. Warden reads the machine before it answers.
          </span>
        </div>
      </div>

      {said && (
        <div className="mt-6 max-w-2xl space-y-3">
          <div className="rounded-xl border border-hairline bg-sunken p-3.5">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              You said
            </div>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{said.you}</p>
          </div>
          <div className="rounded-xl border border-hairline bg-surface p-3.5">
            <div className="flex items-center gap-2">
              <span className="text-series-1">
                <Icon name="shield" size={16} />
              </span>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                Warden
              </div>
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink">{said.warden}</p>
            <p className="mt-2.5 border-t border-hairline pt-2.5 text-[12px] leading-relaxed text-muted">
              This opened a real incident. If Warden has something to propose it is
              waiting on the Now page, with the command and the evidence, and it will
              not run until you approve it.
            </p>
          </div>
        </div>
      )}

      <div className="mt-8 max-w-2xl border-t border-hairline pt-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          What this is, and is not
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
          It is not a chat window with an assistant in it. What you type becomes a
          symptom, exactly like one a detector raised, and goes through the same
          reasoning, the same refusals and the same approval gate. Warden will still tell
          you when it cannot fix something, and it still will not run anything without
          being asked.
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
          It works best with the cloud model on, because describing an arbitrary problem
          usually lands outside the seventeen reviewed actions. Without it, Warden will
          often say honestly that it has nothing to offer, which is the answer the local
          model is allowed to give.
        </p>
      </div>
    </div>
  );
}
