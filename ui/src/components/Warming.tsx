import type { LogLine } from "../lib/useWarden";
import { Logo } from "./Logo";

/**
 * What the window shows while Warden is starting up.
 *
 * Startup takes a while on a new install -- PowerShell autoloads its
 * networking and storage modules, and the first `Get-PhysicalDisk` alone costs
 * several seconds on a cold file cache. That work used to happen before the
 * window could exist at all, so the whole cost was paid in front of a person
 * looking at a taskbar icon and nothing else.
 *
 * Now the window opens immediately and this stands in its place. It is not a
 * spinner: it names the steps and ticks them off, because a product whose
 * entire argument is "we show you what we are doing" should not open with an
 * unexplained wait.
 */
export function Warming({ log }: { log: LogLine[] }) {
  const latest = log[0]?.text;

  return (
    <div className="flex h-full flex-col items-center justify-center gap-7 px-6">
      <Logo size={64} className="pulse" />

      <div className="text-center">
        <h1 className="text-[20px] font-semibold tracking-tight text-ink">
          Taking the first readings
        </h1>
        <p className="mx-auto mt-1.5 max-w-sm text-[13px] leading-relaxed text-ink-2">
          Warden is asking Windows for the things it needs. This takes a few seconds the
          first time on a new machine, and is quick after that.
        </p>
      </div>

      {/* The actual agent log, not invented reassurance. If startup stalls, the
          last real line is the most useful thing on the screen. */}
      {latest && (
        <p className="max-w-md truncate text-center font-mono text-[11px] text-muted">
          {latest}
        </p>
      )}

      <p className="max-w-sm text-center text-[11px] leading-relaxed text-muted">
        Nothing is being changed on your computer. Warden only reads until you approve
        something.
      </p>
    </div>
  );
}
