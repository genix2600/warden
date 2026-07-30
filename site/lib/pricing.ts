/**
 * Pricing, and the reasoning behind it.
 *
 * The constraint that shapes everything here: Warden cannot charge for finding
 * problems. The standard model in this category is detect-free, charge-to-fix,
 * and it creates an incentive to find problems. That incentive is exactly how PC
 * optimisers ended up inventing them. Taking that route would turn Warden into
 * the thing it was built against, so detection and repair are both free on the
 * machine you own, permanently.
 *
 * What is left to sell is managing machines that are not yours. A person fixing
 * their own laptop is not a customer. A person responsible for thirty laptops
 * has a scheduling, reporting and evidence problem that Warden is unusually well
 * placed to solve, because it already records every reading, decision and
 * outcome to a session file.
 *
 * Everything marked `available: false` is unbuilt, and the interface says so
 * twice. A pricing page implying capabilities the software lacks would undercut
 * the one thing the product actually sells.
 */

export interface Tier {
  name: string;
  price: string;
  cadence: string;
  summary: string;
  cta: string;
  href: string | null;
  highlight: boolean;
  available: boolean;
  features: string[];
}

export const TIERS: Tier[] = [
  {
    name: "Free",
    price: "₹0",
    cadence: "forever, per machine",
    summary: "Everything Warden does today, on a machine you own.",
    cta: "Download",
    href: null,
    highlight: true,
    available: true,
    features: [
      "All 13 areas watched continuously",
      "All 17 fixes, each with evidence and your approval",
      "Local AI model included, works offline",
      "Verification after every fix, including when it failed",
      "Tune-up: 9 settings checks, with undo",
      "Session history you can reopen",
      "Open source, no account, no telemetry",
    ],
  },
  {
    name: "Pro",
    price: "₹99",
    cadence: "per month",
    summary: "For the person everyone in the family calls.",
    cta: "Not built yet",
    href: null,
    highlight: false,
    available: false,
    features: [
      "Everything in Free, on up to 5 machines",
      "Scheduled audits with a weekly summary",
      "Export a session as a report to hand someone",
      "A larger local model on machines that can run one",
      "Restore points kept and labelled per change",
    ],
  },
  {
    name: "Team",
    price: "₹199",
    cadence: "per machine, per month",
    summary: "For an IT desk that would rather not walk to every desk.",
    cta: "Not built yet",
    href: null,
    highlight: false,
    available: false,
    features: [
      "Everything in Pro",
      "Fleet view across managed machines",
      "Policy: which actions may be approved, and by whom",
      "Audit trail export, because the evidence already exists",
      "Deployment through your existing tooling",
      "Priority on issue reports",
    ],
  },
];

/** The arithmetic, shown rather than asserted. */
export const ECONOMICS = [
  {
    label: "Cost to serve a free user",
    value: "₹0",
    note: "The model runs on their processor. No inference bill, no storage, no account. A free user costs bandwidth for one download.",
  },
  {
    label: "What a callout costs today",
    value: "₹1,500 to ₹3,000",
    note: "Typical Indian on-site rate for a business machine, most of which is travel and diagnosis rather than the fix.",
  },
  {
    label: "Break-even for a Team seat",
    value: "three avoided callouts a month",
    note: "At ₹199 per machine per month, a 30-machine desk pays ₹71,640 a year. Three callouts a month at ₹2,000 is ₹72,000.",
  },
  {
    label: "Gross margin at scale",
    value: "high, and boring",
    note: "There is no per-user compute. Cost is engineering, code signing, and support. That is the upside of refusing to put the model in a datacentre.",
  },
];
