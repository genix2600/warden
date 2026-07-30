import Link from "next/link";
import { CountUp, Reveal, SplitText, SpotlightCard } from "@/components/motion";
import { DOMAINS, DOWNLOAD_URL, INSTALLER_SIZE, REFUSALS, REPO, STATS } from "@/lib/product";

export default function Home() {
  return (
    <>
      <Hero />
      <Problem />
      <Loop />
      <TuneUp />
      <Refusals />
      <Coverage />
      <Closing />
    </>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-hairline">
      <div aria-hidden className="plane-grid absolute inset-0" />
      <div className="relative mx-auto max-w-4xl px-5 pb-20 pt-20 text-center sm:pt-28">
        <p className="rise text-[12px] font-semibold uppercase tracking-[0.18em] text-series-1">
          Windows 10 &amp; 11 · runs entirely offline
        </p>

        <h1 className="mt-5 text-[40px] font-bold leading-[1.08] tracking-tight text-ink sm:text-[62px]">
          <SplitText text="Your computer can" />{" "}
          <SplitText text="tell you what is wrong." delay={260} />
        </h1>

        <p className="rise mx-auto mt-6 max-w-2xl text-[17px] leading-relaxed text-ink-2">
          Warden reads real signals off your machine, works out the cause, and proposes{" "}
          <strong className="font-semibold text-ink">one specific command</strong> with the
          readings that justify it. It asks before running anything, then re-measures to
          check it actually worked.
        </p>

        <div className="rise mt-9 flex flex-wrap items-center justify-center gap-3">
          <a
            href={DOWNLOAD_URL}
            className="rounded-xl bg-series-1 px-6 py-3 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
          >
            Download for Windows
          </a>
          <Link
            href="/how-it-works"
            className="rounded-xl border border-hairline px-6 py-3 text-[15px] font-medium text-ink-2 transition-colors hover:bg-raised hover:text-ink"
          >
            See how it works
          </Link>
        </div>
        <p className="rise mt-3 text-[12px] text-muted">
          Free · {INSTALLER_SIZE} · the AI runs on your machine, so nothing you look at
          leaves it
        </p>

        <div className="mt-16 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STATS.map((stat, index) => (
            <Reveal key={stat.label} delay={index * 90}>
              <div className="rounded-xl border border-hairline bg-surface px-3 py-4">
                <div className="font-mono text-[26px] font-semibold tabular-nums text-ink">
                  <CountUp to={stat.value} suffix={stat.suffix} />
                </div>
                <div className="mt-1 text-[11px] leading-snug text-muted">{stat.label}</div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Problem() {
  const items = [
    {
      title: "Built-in troubleshooters find nothing",
      body: 'You run the Windows troubleshooter. It thinks for a while and says "Troubleshooting couldn\'t identify the problem." You are exactly where you started, minus five minutes.',
    },
    {
      title: "Chatbots cannot see your computer",
      body: "An AI assistant can discuss your symptoms, but it cannot read your event log, check what is installed, or confirm a fix worked. You end up being its hands and its eyes.",
    },
    {
      title: '"Optimisers" invent problems to sell you',
      body: "Scan, find 4,182 issues, pay to fix. The issues are registry keys that do nothing, and the improvement is unmeasurable. That is the point: an unfalsifiable claim cannot be checked.",
    },
  ];

  return (
    <section className="border-b border-hairline">
      <div className="mx-auto max-w-6xl px-5 py-16">
        <Reveal>
          <h2 className="max-w-2xl text-[28px] font-bold leading-tight tracking-tight text-ink">
            Everything that is supposed to help does one of three things.
          </h2>
        </Reveal>
        <div className="mt-8 grid gap-3 md:grid-cols-3">
          {items.map((item, index) => (
            <Reveal key={item.title} delay={index * 100}>
              <SpotlightCard className="h-full p-5">
                <h3 className="text-[15px] font-semibold text-ink">{item.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{item.body}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Loop() {
  const steps = [
    {
      n: "01",
      title: "Reads",
      body: "Fourteen collectors sample the machine continuously: wireless state, temperatures, drive health, services, the event log, privacy settings.",
    },
    {
      n: "02",
      title: "Reasons",
      body: "A local AI model, running on your machine, picks the most likely cause from what was actually measured. No internet, no account, no key.",
    },
    {
      n: "03",
      title: "Asks",
      body: "You see the exact command, what it will do, and the test that will decide whether it worked, all before you approve. No timer, no default.",
    },
    {
      n: "04",
      title: "Proves",
      body: 'After running, Warden re-reads the machine and evaluates that test. "Fixed" is a measurement. If it failed, it says so and tries the next thing.',
    },
  ];

  return (
    <section className="border-b border-hairline bg-sunken">
      <div className="mx-auto max-w-6xl px-5 py-16">
        <Reveal>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-series-1">
            The loop
          </p>
          <h2 className="mt-2 max-w-2xl text-[28px] font-bold leading-tight tracking-tight text-ink">
            The last step is the one nobody else does.
          </h2>
        </Reveal>

        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step, index) => (
            <Reveal key={step.n} delay={index * 90}>
              <SpotlightCard className="h-full p-5">
                <span className="font-mono text-[12px] text-series-1">{step.n}</span>
                <h3 className="mt-2 text-[16px] font-semibold text-ink">{step.title}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{step.body}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>

        <Reveal delay={200}>
          <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
            <p className="text-[13px] leading-relaxed text-ink-2">
              <strong className="font-semibold text-ink">
                The model never writes a command.
              </strong>{" "}
              It chooses an id from a fixed list of seventeen reviewed actions, and the
              parameters are checked against what was actually observed on your machine.
              Warden will not connect you to a network it has never seen you use, or restart
              a device that is not there.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/** The audit. Its selling point is the two rules it refuses to break, so the
 *  section leads with those rather than with the number of checks. */
function TuneUp() {
  const rules = [
    {
      title: "If it cannot be measured, it is not listed",
      body: "Every finding names a quantity Warden read before and can read again after. There is nothing here whose benefit is a feeling.",
    },
    {
      title: "If it cannot be undone, it is not offered",
      body: "Warden will tell you it found 1.2 GB of temporary files. It will not delete them, because deleting them cannot be reversed, so it cannot be offered under this rule. It suggests turning on Storage Sense instead.",
    },
    {
      title: "If there is no right answer, it does not pick one",
      body: "A capped processor is faster unplugged or quieter on your lap. Warden shows both costs and recommends neither, because it cannot know which you wanted.",
    },
  ];

  return (
    <section className="border-b border-hairline">
      <div className="mx-auto max-w-6xl px-5 py-16">
        <Reveal>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-series-1">
            Tune-up
          </p>
          <h2 className="mt-2 max-w-2xl text-[28px] font-bold leading-tight tracking-tight text-ink">
            Nine settings that are wrong without anything being broken.
          </h2>
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-2">
            A processor capped at 60 per cent by a power plan nobody chose. Graphics
            drivers four years old. Automatic cleanup switched off. None of it is failing,
            which is exactly why nobody has found it. Warden checks on request, shows the
            reading, and can change it back.
          </p>
        </Reveal>

        <div className="mt-8 grid gap-3 md:grid-cols-3">
          {rules.map((rule, index) => (
            <Reveal key={rule.title} delay={index * 100}>
              <SpotlightCard className="h-full p-5">
                <h3 className="text-[15px] font-semibold text-ink">{rule.title}</h3>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{rule.body}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>

        <Reveal delay={220}>
          <div className="mt-6 rounded-xl border border-hairline bg-surface p-5">
            <p className="text-[13px] leading-relaxed text-ink-2">
              <strong className="font-semibold text-ink">
                And afterwards it tells you the truth about the result.
              </strong>{" "}
              Warden re-reads the same number and reports the difference, including when
              the difference is nothing. &ldquo;No measurable change yet&rdquo; is a
              result it is willing to print, which is the whole reason to believe it the
              rest of the time.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Refusals() {
  return (
    <section className="border-b border-hairline">
      <div className="mx-auto max-w-6xl px-5 py-16">
        <Reveal>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-serious">
            What it refuses to do
          </p>
          <h2 className="mt-2 max-w-2xl text-[28px] font-bold leading-tight tracking-tight text-ink">
            Seven problems Warden will not pretend to fix.
          </h2>
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-2">
            Not a disclaimer. It is a list enforced in the code: for these, the set of available
            actions is literally empty, so nothing can select one however confident it is.
          </p>
        </Reveal>

        <div className="mt-8 grid gap-3 md:grid-cols-2">
          {REFUSALS.slice(0, 4).map((item, index) => (
            <Reveal key={item.code} delay={index * 80}>
              <div className="h-full rounded-xl border border-hairline bg-surface p-4">
                <div className="flex items-baseline gap-2">
                  <span aria-hidden className="text-serious">
                    ▲
                  </span>
                  <h3 className="text-[14px] font-semibold text-ink">{item.plain}</h3>
                </div>
                <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">{item.why}</p>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={240}>
          <Link
            href="/what-it-covers"
            className="mt-5 inline-block text-[14px] font-medium text-series-1 hover:underline"
          >
            See all seven, and the seventeen it will do →
          </Link>
        </Reveal>
      </div>
    </section>
  );
}

function Coverage() {
  return (
    <section className="border-b border-hairline bg-sunken">
      <div className="mx-auto max-w-6xl px-5 py-16">
        <Reveal>
          <h2 className="max-w-2xl text-[28px] font-bold leading-tight tracking-tight text-ink">
            Thirteen areas, in the words you would use for them.
          </h2>
        </Reveal>
        <div className="mt-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {DOMAINS.map((domain, index) => (
            <Reveal key={domain.label} delay={Math.min(index * 40, 320)}>
              <div className="h-full rounded-lg border border-hairline bg-surface px-4 py-3">
                <h3 className="text-[13px] font-semibold text-ink">{domain.label}</h3>
                <p className="mt-0.5 text-[12px] leading-snug text-muted">{domain.blurb}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Closing() {
  return (
    <section className="relative overflow-hidden">
      <div aria-hidden className="plane-grid absolute inset-0" />
      <div className="relative mx-auto max-w-3xl px-5 py-20 text-center">
        <Reveal>
          <h2 className="text-[32px] font-bold leading-tight tracking-tight sm:text-[40px]">
            <span className="sheen">Stop guessing at your own computer.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-ink-2">
            Install it, open it, and read what it found. It will not change anything until
            you say so.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <a
              href={DOWNLOAD_URL}
              className="rounded-xl bg-series-1 px-6 py-3 text-[15px] font-semibold text-white transition-opacity hover:opacity-90"
            >
              Download for Windows
            </a>
            <a
              href={REPO}
              className="rounded-xl border border-hairline px-6 py-3 text-[15px] font-medium text-ink-2 transition-colors hover:bg-raised hover:text-ink"
            >
              Read the source
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
