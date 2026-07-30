import type { Metadata } from "next";
import { Callout, PageShell, Prose, Section } from "@/components/ui";
import { DOWNLOAD_URL } from "@/lib/product";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Warden is free and open source today. These tiers show the intended shape of a "
    + "commercial product; nothing is for sale yet.",
};

/**
 * Illustrative tiers.
 *
 * Every feature listed under Free is built and working today. Everything under
 * Pro and Team is explicitly marked as not built, because a pricing page that
 * quietly implies capabilities the product does not have would undermine the
 * one thing Warden actually sells -- that it does not overstate what it knows.
 */
const TIERS = [
  {
    name: "Free",
    price: "£0",
    cadence: "forever",
    summary: "Everything Warden does today, on your own machine.",
    cta: "Download",
    href: DOWNLOAD_URL,
    highlight: true,
    available: true,
    features: [
      "All 13 areas watched continuously",
      "All 15 fixes, each with evidence and approval",
      "Local AI model included, works offline",
      "Verification after every fix",
      "Tune-up: settings that are measurably wrong",
      "Session history you can reopen",
      "Open source, no account, no telemetry",
    ],
  },
  {
    name: "Pro",
    price: "£4",
    cadence: "per month",
    summary: "For someone who looks after a few machines that are not theirs.",
    cta: "Not available yet",
    href: null,
    highlight: false,
    available: false,
    features: [
      "Everything in Free",
      "Scheduled audits with an emailed summary",
      "Export a session as a report to hand someone",
      "Larger local model for better explanations",
      "Priority on issue reports",
    ],
  },
  {
    name: "Team",
    price: "Talk to us",
    cadence: "",
    summary: "For an IT desk that would rather not walk to every machine.",
    cta: "Not available yet",
    href: null,
    highlight: false,
    available: false,
    features: [
      "Everything in Pro",
      "Fleet view across managed machines",
      "Policy: which actions may be approved by whom",
      "Audit trail export for compliance",
      "Deployment via your existing tooling",
    ],
  },
];

export default function PricingPage() {
  return (
    <PageShell
      eyebrow="Pricing"
      title="Free today, and the free tier is the whole product"
      lead="Warden is a student project. It is open source and costs nothing, and everything described on this site is in the free version."
    >
      <Callout tone="warning" title="These tiers are illustrative">
        <p>
          Pro and Team describe where this would go if it became a real product. They are{" "}
          <strong className="text-ink">not for sale</strong>, there is no payment page behind
          them, and the features listed under them are <strong className="text-ink">not
          built</strong>. They are here to show the intended shape, not to take your money.
        </p>
        <p className="mt-2">
          A pricing page that quietly implied capabilities the software does not have would
          undercut the one thing Warden is actually selling.
        </p>
      </Callout>

      <section className="grid gap-3 lg:grid-cols-3">
        {TIERS.map((tier) => (
          <div
            key={tier.name}
            className={`flex flex-col rounded-xl border p-5 ${
              tier.highlight
                ? "border-series-1/50 bg-surface"
                : "border-hairline bg-surface opacity-90"
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
              <span className="text-[30px] font-bold tracking-tight text-ink">{tier.price}</span>
              {tier.cadence && <span className="text-[13px] text-muted">{tier.cadence}</span>}
            </div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{tier.summary}</p>

            <ul className="mt-4 flex-1 space-y-1.5">
              {tier.features.map((feature) => (
                <li key={feature} className="flex gap-2 text-[13px] leading-snug text-ink-2">
                  <span
                    aria-hidden
                    className={tier.available ? "text-good" : "text-muted"}
                  >
                    ✓
                  </span>
                  {feature}
                </li>
              ))}
            </ul>

            {tier.href ? (
              <a
                href={tier.href}
                className="mt-5 rounded-lg bg-series-1 px-4 py-2.5 text-center text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              >
                {tier.cta}
              </a>
            ) : (
              <span className="mt-5 cursor-not-allowed rounded-lg border border-hairline px-4 py-2.5 text-center text-[14px] text-muted">
                {tier.cta}
              </span>
            )}
          </div>
        ))}
      </section>

      <Section title="Why the free tier is not crippled">
        <Prose>
          <p>
            The usual model for software like this is to detect problems for free and charge to
            fix them. That creates an incentive to find problems, which is exactly how PC
            optimisers ended up inventing them.
          </p>
          <p>
            Warden cannot take that route without becoming the thing it was built against, so
            it does not. Detection and repair are both free, and always will be. If a paid tier
            ever exists it will be for managing machines that are not yours: scheduling,
            reporting, fleets. Not for permission to fix your own.
          </p>
        </Prose>
      </Section>
    </PageShell>
  );
}
