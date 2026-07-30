import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ReasonerStatus } from "../types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusDot } from "../components/StatusDot";

/**
 * Which brain answers, and what each one costs you.
 *
 * This page exists because the choice is not a preference. Warden's whole
 * argument is that it does not overstate, and the difference between the two
 * models is precisely the sort of thing a product overstates by omission: one
 * of them sends readings from this machine to a company in another country.
 * Burying that in a settings toggle labelled "Use cloud AI" would be the lie.
 *
 * So the page is laid out as a comparison rather than as a switch. Both columns
 * state what they can do and what they cost, in the same words and the same
 * weight, and the internet requirement is on screen before the key field is.
 */
export function Model() {
  const [status, setStatus] = useState<ReasonerStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.reasoner());
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.setKey(key.trim()));
      setKey("");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.clearKey());
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  const cloudOn = status?.cloud_enabled === true;

  return (
    <div className="scroll-y h-full px-6 py-5">
      <PageHeader
        title="Model"
        subtitle="Which brain answers when Warden reasons about a problem, and what each one costs."
      />

      {error && <p className="mb-4 text-[13px] text-critical">{error}</p>}

      <div className="grid gap-3 lg:grid-cols-2">
        <Brain
          title="On this machine"
          badge={status?.local_available ? "Ready" : "Not installed"}
          tone={status?.local_available ? "good" : "idle"}
          active={!cloudOn}
          model={status?.local_model ?? null}
          can={[
            "Picks from the 17 reviewed actions, and cannot write a command",
            "Works with the network down, which is when you need it most",
            "Nothing leaves this machine, ever",
          ]}
          costs={[
            "Slower: 15 to 19 seconds for a decision on a laptop",
            "Cannot help with anything outside those 17 actions",
          ]}
        />
        <Brain
          title="Groq, over the internet"
          badge={cloudOn ? "On" : "Off"}
          tone={cloudOn ? "warning" : "idle"}
          active={cloudOn}
          model={status?.cloud_model ?? null}
          can={[
            "Knows the Windows command line properly",
            "Can write a command when none of the 17 fit",
            "Answers in two to four seconds",
          ]}
          costs={[
            "Requires an internet connection, so it cannot fix a broken one",
            "Sends readings from this machine to Groq",
            "Needs your own API key, and Groq's terms apply to what is sent",
          ]}
        />
      </div>

      {/* Stated before the key field rather than after it. Someone who reads
          only the first thing on this section should still have been told. */}
      <section className="mt-4 rounded-xl border border-warning/40 bg-surface p-4">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 text-warning">
            <Icon name="shield" size={18} />
          </span>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-ink">
              Turning this on sends data off your computer
            </h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
              When the cloud model answers, Warden sends it the readings behind the
              problem: what the symptom is, what the collectors measured, your Windows
              version, and the list of actions it may choose from. It does not send your
              files, your browsing, your account names or anything Warden has not itself
              measured.
            </p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
              It also needs a working internet connection, which means it is exactly no
              use for the fault Warden was built for. The local model stays as the
              fallback for that reason, and Warden drops back to it automatically.
            </p>
          </div>
        </div>
      </section>

      <section className="mt-3 rounded-xl border border-hairline bg-surface p-4">
        <h2 className="text-[14px] font-semibold text-ink">
          {cloudOn ? "Your key" : "Add a Groq key"}
        </h2>

        {cloudOn ? (
          <div className="mt-2.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <StatusDot tone={status?.cloud_reachable ? "good" : "critical"} />
              <code className="rounded bg-sunken px-2 py-1 font-mono text-[12px] text-ink-2">
                {status?.cloud_key_hint || "stored"}
              </code>
              <span className="text-[12px] text-muted">
                {status?.cloud_reachable
                  ? `answering as ${status.cloud_model}`
                  : "stored, but Groq is not answering right now"}
              </span>
              <button
                type="button"
                onClick={() => void remove()}
                disabled={busy}
                className="ml-auto rounded-lg border border-hairline px-3 py-1.5 text-[12px] text-ink-2 transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
              >
                Remove key and switch off
              </button>
            </div>
            <p className="mt-2.5 text-[12px] leading-relaxed text-muted">
              Kept in{" "}
              <code className="font-mono">%LOCALAPPDATA%\Warden\credentials.json</code>, in
              its own file rather than with your settings, and never sent anywhere except
              to Groq. Warden only ever shows you the last four characters. Removing it
              deletes the file.
            </p>
          </div>
        ) : (
          <div className="mt-2.5">
            <p className="text-[13px] leading-relaxed text-ink-2">
              Get one free from{" "}
              <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px]">
                console.groq.com/keys
              </code>
              . Warden does not ship with a key and never will: this repository is public,
              so a key in it would be a key for everybody.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <input
                type="password"
                value={key}
                onChange={(event) => setKey(event.target.value)}
                placeholder="gsk_..."
                spellCheck={false}
                autoComplete="off"
                className="min-w-0 flex-1 rounded-lg border border-hairline bg-sunken px-3 py-2 font-mono text-[13px] text-ink outline-none placeholder:text-muted focus:border-series-1"
              />
              <button
                type="button"
                onClick={() => void save()}
                disabled={busy || key.trim().length < 8}
                className="rounded-lg bg-series-1 px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {busy ? "Checking…" : "Turn on cloud mode"}
              </button>
            </div>
            <p className="mt-2 text-[12px] text-muted">
              Warden checks the key against Groq before saving it. A key that does not work
              is not stored.
            </p>
          </div>
        )}
      </section>

      <section className="mt-3 rounded-xl border border-hairline bg-sunken p-4">
        <h2 className="text-[13px] font-semibold text-ink">
          What changes when the cloud model is on
        </h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
          It may write a command instead of picking one from the reviewed list. Those are
          labelled differently everywhere they appear, because they are different: a
          reviewed action was read by a person, is checked against what was actually
          measured on your machine, and declares in advance the test that will decide
          whether it worked. A written command has none of that.
        </p>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
          Warden still refuses to run a written command that wipes a disk, deletes your
          restore points, switches off Defender or the firewall, creates an account, or
          downloads and runs something. Those refusals happen before you are shown a
          button, so you are never asked to judge them.
        </p>
      </section>
    </div>
  );
}

function Brain({
  title,
  badge,
  tone,
  active,
  model,
  can,
  costs,
}: {
  title: string;
  badge: string;
  tone: "good" | "warning" | "idle";
  active: boolean;
  model: string | null;
  can: string[];
  costs: string[];
}) {
  return (
    <article
      className={`rounded-xl border bg-surface p-4 ${
        active ? "border-series-1/50" : "border-hairline"
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        <StatusDot tone={tone === "idle" ? "idle" : tone} />
        <span className="text-[11px] text-muted">{badge}</span>
        {active && (
          <span className="ml-auto rounded border border-series-1/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-series-1">
            Answering now
          </span>
        )}
      </header>
      {model && (
        <code className="mt-2 block truncate font-mono text-[11px] text-muted">{model}</code>
      )}

      <h3 className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">
        What it can do
      </h3>
      <ul className="mt-1 space-y-1">
        {can.map((line) => (
          <li key={line} className="flex gap-2 text-[12px] leading-snug text-ink-2">
            <span aria-hidden className="text-good">
              +
            </span>
            {line}
          </li>
        ))}
      </ul>

      <h3 className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-muted">
        What it costs
      </h3>
      <ul className="mt-1 space-y-1">
        {costs.map((line) => (
          <li key={line} className="flex gap-2 text-[12px] leading-snug text-ink-2">
            <span aria-hidden className="text-warning">
              −
            </span>
            {line}
          </li>
        ))}
      </ul>
    </article>
  );
}
