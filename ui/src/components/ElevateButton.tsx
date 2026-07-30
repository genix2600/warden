import { useState } from "react";
import { api } from "../lib/api";
import { Icon } from "./Icon";

/**
 * "Restart as administrator", offered where the user meets the limit.
 *
 * Warden does not demand elevation to start. A managed laptop where the user is
 * not an administrator is exactly the kind of machine most likely to have
 * something quietly misconfigured, and refusing to open on it would be the
 * wrong trade. So it runs for everyone, says plainly which actions it cannot
 * perform, and puts this button next to that sentence rather than in a settings
 * page nobody opens.
 *
 * Declining the Windows prompt is a legitimate answer, and the message says so
 * without implying anything has gone wrong.
 */
export function ElevateButton({ compact = false }: { compact?: boolean }) {
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const restart = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.relaunchElevated();
      setMessage(result.detail);
    } catch (problem) {
      setMessage(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={compact ? "" : "mt-2"}>
      <button
        type="button"
        onClick={() => void restart()}
        disabled={busy}
        className={`inline-flex items-center gap-1.5 rounded-lg border border-series-1/50 text-series-1 transition-colors hover:bg-raised disabled:opacity-50 ${
          compact ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-[12px]"
        }`}
      >
        <Icon name="shield" size={compact ? 12 : 14} />
        {busy ? "Asking Windows…" : "Restart as administrator"}
      </button>
      {message && <p className="mt-1.5 text-[11px] leading-relaxed text-muted">{message}</p>}
    </div>
  );
}
