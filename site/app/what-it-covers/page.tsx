import type { Metadata } from "next";
import { PageShell, Prose, Section } from "@/components/ui";
import { ACTION_TIERS, DOMAINS, REFUSALS } from "@/lib/product";

export const metadata: Metadata = {
  title: "What it covers",
  description:
    "Thirteen areas of Windows, fifteen actions across three risk tiers, and the seven "
    + "problems Warden refuses to attempt.",
};

export default function WhatItCoversPage() {
  return (
    <PageShell
      eyebrow="Capabilities and limits"
      title="Everything it can do, and everything it will not"
      lead="A tool asking permission to run commands on your computer should be able to state its own limits precisely, before it is asked."
    >
      <Section
        title="Thirteen areas"
        blurb="Warden watches these continuously and reports each one in plain English, including when it could not get a reading."
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {DOMAINS.map((domain) => (
            <div
              key={domain.label}
              className="rounded-lg border border-hairline bg-surface px-4 py-3"
            >
              <h3 className="text-[13px] font-semibold text-ink">{domain.label}</h3>
              <p className="mt-0.5 text-[12px] leading-snug text-muted">{domain.blurb}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="Fifteen actions, grouped by how much they disturb"
        blurb="This is the complete list. There is no other way for Warden to change your machine, and every one of them shows you the exact command before you approve it."
      >
        <div className="space-y-3">
          {ACTION_TIERS.map((tier) => (
            <div key={tier.tier} className="rounded-xl border border-hairline bg-surface p-4">
              <div className="flex flex-wrap items-baseline gap-2">
                <h3 className="text-[15px] font-semibold text-ink">{tier.tier}</h3>
                <span className="font-mono text-[12px] text-series-1">{tier.count} actions</span>
              </div>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{tier.blurb}</p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {tier.examples.map((example) => (
                  <code
                    key={example}
                    className="rounded border border-hairline bg-sunken px-2 py-0.5 font-mono text-[11px] text-ink-2"
                  >
                    {example}
                  </code>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="Seven problems it refuses to fix"
        blurb="Enforced in the code, not by good intentions. For each of these the list of available actions is empty, so no amount of model confidence can produce one."
      >
        <div className="space-y-2.5">
          {REFUSALS.map((item) => (
            <div
              key={item.code}
              className="rounded-xl border border-serious/30 bg-surface p-4"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span aria-hidden className="text-serious">
                  ▲
                </span>
                <h3 className="text-[14px] font-semibold text-ink">{item.plain}</h3>
                <code className="font-mono text-[11px] text-muted">{item.code}</code>
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{item.why}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Things it will never do at all">
        <Prose>
          <p>
            Some popular features are absent on purpose, and all for the same reason: their
            effect cannot be measured, so their claim cannot be checked.
          </p>
        </Prose>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <Never
            what="Registry cleaning"
            why="No measurable benefit has ever been demonstrated. It is scareware's signature move."
          />
          <Never
            what="Disabling services for speed"
            why="Trades reliability you will notice for milliseconds you will not."
          />
          <Never
            what="Removing built-in apps"
            why="Not a fault, and not Warden's decision to make on your behalf."
          />
          <Never
            what="Malware removal"
            why="Cannot be done safely or verifiably. Warden reports what Defender says and stops."
          />
          <Never
            what="Installing drivers"
            why="It will tell you a driver is years old. Fetching one is between you and the vendor."
          />
          <Never
            what="Anything phrased as 'up to X% faster'"
            why="If the number cannot be re-measured afterwards, it is marketing."
          />
        </div>
      </Section>
    </PageShell>
  );
}

function Never({ what, why }: { what: string; why: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-sunken px-4 py-3">
      <h3 className="text-[13px] font-semibold text-ink">{what}</h3>
      <p className="mt-0.5 text-[12px] leading-snug text-muted">{why}</p>
    </div>
  );
}
