import { useState } from "react";
import { api } from "../lib/api";
import { Icon } from "./Icon";

/**
 * "Download the local model", offered on Readiness and never taken automatically.
 *
 * The standard build leaves the model weights out: about 160 MB instead of
 * nearly a gigabyte, which is the difference between someone trying Warden and
 * someone closing the tab. The model is fetched on request afterwards.
 *
 * On request, and not on first launch, for the same reason nothing else here
 * happens without asking. Warden is genuinely useful without it -- the rules
 * engine answers every scenario end to end -- so spending a gigabyte of
 * somebody's bandwidth is a decision that belongs to them, not something that
 * happens because they opened an application.
 *
 * Progress is reported through the ordinary agent log rather than a bespoke
 * progress bar, so a slow download looks like everything else Warden narrates.
 */
export function GetModelButton() {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.downloadModel();
      setMessage(result.detail);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => void download()}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg border border-series-1/50 px-3 py-1.5 text-[12px] text-series-1 transition-colors hover:bg-raised disabled:opacity-50"
      >
        <Icon name="download" size={14} />
        {busy ? "Downloading… watch the log" : "Download the model (about 1 GB)"}
      </button>
      {message && <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{message}</p>}
      {busy && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
          This takes a few minutes. You can keep using Warden while it runs, and the
          rules engine answers in the meantime.
        </p>
      )}
    </div>
  );
}
