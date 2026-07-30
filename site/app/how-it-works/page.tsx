import type { Metadata } from "next";
import { Callout, PageShell, Prose, Section } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "How it works",
  description:
    "Collectors read the machine, detectors turn readings into symptoms, a local model "
    + "picks from a closed list of actions, you approve, and the fix is re-measured.",
};

const STAGES = [
  {
    n: "01",
    title: "It reads the machine",
    body: "Fourteen collectors sample continuously, each on its own schedule: wireless every two seconds, drive health every minute. Every reading carries the exact command that produced it, how long that took, and how much the collector trusts it. Nothing is inferred at this stage and nothing is judged.",
  },
  {
    n: "02",
    title: "Readings become symptoms",
    body: "Plain rules, no AI. A condition has to hold across consecutive samples before it counts, so a wireless blip is not an incident. When one fault causes several, the root cause suppresses the rest, because otherwise you get four alarms for one problem.",
  },
  {
    n: "03",
    title: "A local model explains it",
    body: "The model receives the symptom, the readings that support it, and a short list of permitted actions. It writes the explanation and picks one action. It runs on your processor, so this works with the network down. That matters, because the network being down is one of the things Warden fixes.",
  },
  {
    n: "04",
    title: "The guardrail checks the answer",
    body: "The chosen action must be permitted for that specific symptom, so a full disk cannot be answered by restarting the wireless adapter. Parameters are checked against reality: it cannot name a network you have never joined. Anything it refuses is shown to you rather than hidden.",
  },
  {
    n: "05",
    title: "You decide",
    body: "The card shows the exact command, what it will do, why this action, and the test that will decide whether it worked. Nothing happens until you choose, and there is no timer. If the problem resolves itself while it waits, the incident closes having run nothing.",
  },
  {
    n: "06",
    title: "It proves the fix",
    body: 'Warden re-reads the machine and evaluates the test you already approved. Three answers, not two: it worked, it did not, or it could not tell. If it did not work, the incident escalates: the failed action is excluded and the next proposal has to be something else.',
  },
];

export default function HowItWorksPage() {
  return (
    <PageShell
      eyebrow="Architecture"
      title="How Warden actually works"
      lead="Six stages. The interesting ones are the last three, because that is where every other tool stops."
    >
      <section>
        <div className="space-y-2.5">
          {STAGES.map((stage) => (
            <div key={stage.n} className="rounded-xl border border-hairline bg-surface p-5">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-[13px] text-series-1">{stage.n}</span>
                <h2 className="text-[16px] font-semibold text-ink">{stage.title}</h2>
              </div>
              <p className="mt-2 text-[14px] leading-relaxed text-ink-2">{stage.body}</p>
            </div>
          ))}
        </div>
      </section>

      <Section
        title="Why the AI cannot run arbitrary commands"
        blurb="This is the question worth being precise about, because 'an AI that fixes your computer' should worry you."
      >
        <Prose>
          <p>
            <strong className="text-ink">The model never writes a command.</strong> It receives
            a problem and a list of action ids, and all it can output is a choice from that
            list plus some parameters. Every command is hand-written, sits in the source, and
            can be read before you install anything.
          </p>
          <p>Then four checks stand between a choice and a running process:</p>
        </Prose>
        <ol className="mt-3 space-y-2">
          <Gate
            n={1}
            title="Approval"
            body="The execution function cannot be called without a timestamp proving you agreed. There is no default, no override flag, and no code path that supplies one for you. A test asserts this by inspecting the function itself, so a future refactor cannot quietly remove it."
          />
          <Gate
            n={2}
            title="Known action"
            body="The id must name a real entry in the reviewed list."
          />
          <Gate
            n={3}
            title="The command is rebuilt and compared"
            body="The command is generated again, from the template and the parameters, and checked against the one being proposed. If they differ by a character it is refused. Nothing downstream is trusted to hand over a command, not even Warden's own earlier self."
          />
          <Gate
            n={4}
            title="Permissions"
            body="An action needing administrator is refused up front and explained, rather than failing halfway through after you already said yes."
          />
        </ol>
        <p className="mt-3 text-[13px] leading-relaxed text-muted">
          And throughout: commands are passed to Windows as a list of separate arguments, never
          as a line of text handed to a shell. There is no shell in the process, so there is
          nothing to inject into.
        </p>
      </Section>

      <Callout title="Verification is the whole point">
        <p>
          A troubleshooter that reports success without checking is the thing this exists to
          replace. Every action declares its success test <em>before</em> you approve, so you
          are agreeing to the standard as well as the command, and afterwards &ldquo;it&rsquo;s
          fixed&rdquo; is a measurement you already signed off, not a claim you have to take on
          faith.
        </p>
      </Callout>

      <Section title="Read it yourself">
        <Prose>
          <p>
            The source is public. If you only open three files, open these. They carry the
            design.
          </p>
        </Prose>
        <div className="mt-3 space-y-2">
          <SourceLink
            path="warden/contracts/"
            what="Every type that crosses a boundary. The rule that a 'needs a technician' verdict cannot carry a runnable command is enforced here, by the type system, not by convention."
          />
          <SourceLink
            path="warden/playbooks/base.py"
            what="The closed list of actions, each with its command template, its safety checks, and its success test."
          />
          <SourceLink
            path="warden/executor/runner.py"
            what="The only code in Warden that changes anything, and the four gates in front of it."
          />
        </div>
      </Section>
    </PageShell>
  );
}

function Gate({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="flex gap-3 rounded-lg border border-hairline bg-surface p-4">
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-raised font-mono text-[12px] text-series-1">
        {n}
      </span>
      <div>
        <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{body}</p>
      </div>
    </li>
  );
}

function SourceLink({ path, what }: { path: string; what: string }) {
  return (
    <a
      href={`${REPO}/blob/main/${path}`}
      className="block rounded-lg border border-hairline bg-surface p-3.5 transition-colors hover:border-series-1/50"
    >
      <code className="font-mono text-[12px] text-series-1">{path}</code>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{what}</p>
    </a>
  );
}
