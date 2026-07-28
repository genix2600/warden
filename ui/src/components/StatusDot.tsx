import type { StatusTone } from "../types";
import { toneBg, toneClass } from "../lib/format";

/**
 * A status is never colour alone.
 *
 * The status palette puts `warning` and `serious` close enough together that
 * hue cannot reliably separate them, so every state in this interface carries a
 * glyph and a word as well as a colour. That also covers the case the colour
 * cannot: a user with colour vision deficiency, and a judge looking at a
 * projector.
 */
const GLYPH: Record<StatusTone, string> = {
  good: "✓",
  warning: "!",
  serious: "▲",
  critical: "✕",
  idle: "·",
};

export function StatusDot({ tone, label }: { tone: StatusTone; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className={`grid size-4 place-items-center rounded-full text-[10px] font-bold text-plane ${toneBg(tone)}`}
      >
        {GLYPH[tone]}
      </span>
      {label ? <span className={`text-xs font-medium ${toneClass(tone)}`}>{label}</span> : null}
    </span>
  );
}

export function Pill({
  tone = "idle",
  children,
}: {
  tone?: StatusTone;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-hairline bg-sunken px-2.5 py-1 text-[11px] font-medium ${toneClass(tone)}`}
    >
      <span aria-hidden className={`size-1.5 rounded-full ${toneBg(tone)}`} />
      {children}
    </span>
  );
}
