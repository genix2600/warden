import type { LogLine } from "../lib/useWarden";
import { clockTime } from "../lib/format";

const TONE: Record<LogLine["level"], string> = {
  info: "text-ink-2",
  warn: "text-warning",
  error: "text-critical",
};

/**
 * The agent narrating itself.
 *
 * Not decoration: this is the audit trail in prose, and it is written to the
 * session file alongside the structured events. If Warden did something you did
 * not expect, this is where you find out in what order it thought about it.
 */
export function AgentLog({ lines }: { lines: LogLine[] }) {
  return (
    <div className="flex h-full flex-col">
      <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        Agent log
      </h2>
      <ol className="scroll-y flex-1 space-y-1.5 pr-1">
        {lines.length === 0 && <li className="text-[12px] text-muted">nothing yet</li>}
        {lines.map((line) => (
          <li key={line.seq} className="rise text-[12px] leading-snug">
            <span className="mr-2 font-mono text-[10px] text-muted tabular-nums">
              {clockTime(line.ts)}
            </span>
            <span className={TONE[line.level]}>{line.text}</span>
            {line.detail && (
              <div className="ml-[3.25rem] mt-0.5 text-[11px] text-muted">{line.detail}</div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
