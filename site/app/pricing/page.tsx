import type { Metadata } from "next";
import { Reveal, SpotlightCard } from "@/components/motion";
import { Callout, PageShell, Prose, Section } from "@/components/ui";
import { ECONOMICS, TIERS } from "@/lib/pricing";
import { DOWNLOAD_URL } from "@/lib/product";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Warden is free on a machine you own, permanently. Paid tiers are for "
    + "managing machines that are not yours, and are not built yet.",
};

export default function PricingPage() {
  return (
    <PageShell
      eyebrow="Pricing"
      title="Free on your own machine, permanently"
      lead="Not free as a trial, and not free until the interesting part. Detection and repair are both free forever on a machine you own, and the reason is worth more than the price."
    >
      <Callout tone="warning" title="Only the free tier exists">
        <p>
          Pro and Team describe where this goes if it becomes a product. They are{" "}
          <strong className="text-ink">not for sale</strong>, there is no payment page
          behind them, and the features listed under them are{" "}
          <strong className="text-ink">not built</strong>. They are here to show the
          shape, not to take your money.
        </p>
        <p className="mt-2">
          A pricing page implying capabilities the software does not have would undercut
          the one thing Warden is actually selling.
        </p>
      </Callout>

      <section className="grid gap-3 lg:grid-cols-3">
        {TIERS.map((tier, index) => (
          <Reveal key={tier.name} delay={index * 90}>
            <SpotlightCard
              className={`flex h-full flex-col p-5 ${
                tier.highlight ? "border-series-1/50" : "opacity-90"
              }`}
            >
              <div className="flex items-baseline gap-2">
                <h2 className="text-[17px] font-semibold text-ink">{tier.name}</h2>
                {!tier.available && (
                  <span className="rounded border border-hairline px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                    Not built
                  </span>
                )}
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-[30px] font-bold tracking-tight text-ink">
                  {tier.price}
                </span>
                {tier.cadence && (
                  <span className="text-[12px] text-muted">{tier.cadence}</span>
                )}
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{tier.summary}</p>

              <ul className="mt-4 flex-1 space-y-1.5">
                {tier.features.map((feature) => (
                  <li key={feature} className="flex gap-2 text-[13px] leading-snug text-ink-2">
                    <span aria-hidden className={tier.available ? "text-good" : "text-muted"}>
                      ✓
                    </span>
                    {feature}
                  </li>
                ))}
              </ul>

              {tier.available ? (
                <a
                  href={DOWNLOAD_URL}
                  className="mt-5 rounded-lg bg-series-1 px-4 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                >
                  {tier.cta}
                </a>
              ) : (
                <span className="mt-5 cursor-not-allowed rounded-lg border border-hairline px-4 py-2.5 text-center text-[14px] text-muted">
                  {tier.cta}
                </span>
              )}
            </SpotlightCard>
          </Reveal>
        ))}
      </section>

      <Section title="Why finding problems will never cost money">
        <Prose>
          <p>
            The standard model in this category is detect for free and charge to fix.
            It sounds reasonable and it is the root of everything wrong with the
            category, because it pays a company to find problems. Once finding a
            problem is worth money, a scan that returns nothing is a failed sale, and
            the software learns to return something.
          </p>
          <p>
            That is how &ldquo;4,182 issues detected&rdquo; happens. Nobody set out to
            build a scam; they built an incentive and followed it.
          </p>
          <p>
            Warden cannot take that route without becoming the thing it was built
            against, so it does not. Detection and repair are both free on a machine
            you own, and that is a structural commitment rather than a launch
            promotion.
          </p>
        </Prose>
      </Section>

      <Section
        title="What is worth charging for"
        blurb="Not permission to fix your own computer. Managing machines that are not yours."
      >
        <Prose>
          <p>
            A person fixing their own laptop is not a customer. A person responsible
            for thirty laptops has a different problem: they need to know which
            machines need attention without visiting them, and they need a record of
            what was changed and why.
          </p>
          <p>
            Warden already writes that record. Every reading, every decision, every
            approval and every verified outcome goes to a session file, because the
            product needed it to be honest. Turning that into a fleet view and an
            exportable audit trail is a product, and it is one nobody has to be misled
            to buy.
          </p>
        </Prose>
      </Section>

      <Section
        title="The arithmetic"
        blurb="Shown rather than asserted, because a business model with no numbers is a wish."
      >
        <div className="grid gap-2.5 sm:grid-cols-2">
          {ECONOMICS.map((item, index) => (
            <Reveal key={item.label} delay={index * 70}>
              <div className="h-full rounded-xl border border-hairline bg-surface p-4">
                <div className="text-[11px] uppercase tracking-wide text-muted">
                  {item.label}
                </div>
                <div className="mt-1 text-[20px] font-semibold tracking-tight text-ink">
                  {item.value}
                </div>
                <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">{item.note}</p>
              </div>
            </Reveal>
          ))}
        </div>
        <p className="mt-3 max-w-2xl text-[12px] leading-relaxed text-muted">
          The callout figure is a typical Indian on-site rate and worth checking
          against your own market. Everything else follows from Warden running the model on
          the user&rsquo;s own processor, which means a free user costs one download
          and nothing after that.
        </p>
      </Section>
    </PageShell>
  );
}
