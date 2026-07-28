import type { StatusTone } from "../types";

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function since(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

/** A shell-style rendering of an argv array, for display only.
 *
 * Quoting here is cosmetic: the executor never passes this string to anything.
 * It exists so a user can recognise the command, and so they could paste it into
 * a terminal themselves if they would rather run it by hand -- which is a
 * reasonable thing to want and worth supporting.
 */
export function renderArgv(argv: string[]): string {
  return argv.map((token) => (/\s/.test(token) ? `"${token}"` : token)).join(" ");
}

export function severityTone(severity: string): StatusTone {
  if (severity === "critical") return "critical";
  if (severity === "warn") return "warning";
  return "idle";
}

export function stateTone(state: string): StatusTone {
  switch (state) {
    case "resolved":
      return "good";
    case "needs_service":
      return "serious";
    case "unresolved":
      return "critical";
    case "awaiting_approval":
      return "warning";
    case "declined":
      return "idle";
    default:
      return "idle";
  }
}

export function stateLabel(state: string): string {
  return (
    {
      diagnosing: "Diagnosing",
      awaiting_approval: "Waiting for you",
      executing: "Running the fix",
      verifying: "Checking it worked",
      resolved: "Fixed and verified",
      unresolved: "Not resolved",
      needs_service: "Needs a physical fix",
      declined: "Declined",
      monitoring: "Watching",
    }[state] ?? state
  );
}

export function riskLabel(risk: string): string {
  return (
    {
      read_only: "Reads only, changes nothing",
      reversible: "Reversible",
      intrusive: "Disruptive",
    }[risk] ?? risk
  );
}

export function toneClass(tone: StatusTone): string {
  return {
    good: "text-good",
    warning: "text-warning",
    serious: "text-serious",
    critical: "text-critical",
    idle: "text-muted",
  }[tone];
}

export function toneBg(tone: StatusTone): string {
  return {
    good: "bg-good",
    warning: "bg-warning",
    serious: "bg-serious",
    critical: "bg-critical",
    idle: "bg-muted",
  }[tone];
}
