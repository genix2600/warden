import type { ReactNode } from "react";

/** Page scaffolding, so every page below `/` opens the same way. */
export function PageShell({
  eyebrow,
  title,
  lead,
  children,
}: {
  eyebrow?: string;
  title: string;
  lead?: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-4xl px-5 py-14">
      <header className="rise">
        {eyebrow && (
          <p className="text-[11px] font-semibold uppercase tracking-wider text-series-1">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-2 text-[34px] font-bold leading-tight tracking-tight text-ink sm:text-[42px]">
          {title}
        </h1>
        {lead && (
          <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-ink-2">{lead}</p>
        )}
      </header>
      <div className="mt-10 space-y-12">{children}</div>
    </div>
  );
}

export function Section({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb?: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="text-[20px] font-semibold tracking-tight text-ink">{title}</h2>
      {blurb && <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-ink-2">{blurb}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Prose({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-2xl space-y-3 text-[14px] leading-relaxed text-ink-2">{children}</div>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning";
  title: string;
  children: ReactNode;
}) {
  const border = tone === "warning" ? "border-warning/40" : "border-series-1/40";
  const text = tone === "warning" ? "text-warning" : "text-series-1";
  return (
    <div className={`rounded-xl border ${border} bg-surface p-4`}>
      <h3 className={`text-[13px] font-semibold ${text}`}>{title}</h3>
      <div className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px] text-ink-2">
      {children}
    </code>
  );
}

export function CommandBlock({ children }: { children: ReactNode }) {
  return (
    <pre className="overflow-x-auto rounded-lg border border-hairline bg-sunken p-3 font-mono text-[12px] leading-relaxed text-ink-2">
      {children}
    </pre>
  );
}
