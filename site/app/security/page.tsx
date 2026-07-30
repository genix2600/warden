import type { Metadata } from "next";
import { Callout, PageShell, Prose, Section } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "Security & privacy",
  description:
    "Warden runs entirely on your machine. No account, no telemetry, no API keys, and a "
    + "closed list of commands it is able to run.",
};

export default function SecurityPage() {
  return (
    <PageShell
      eyebrow="Security & privacy"
      title="It reads a lot about your computer. None of it leaves."
      lead="Warden looks at your event log, your device inventory, your network configuration and your installed services. That is a great deal of trust to ask for, so here is exactly what happens to it."
    >
      <Section title="Nothing is transmitted">
        <div className="grid gap-2.5 sm:grid-cols-2">
          <Fact
            title="No account"
            body="There is no sign-up, no licence key and no activation. Nothing identifies you because nothing needs to."
          />
          <Fact
            title="No telemetry"
            body="No usage analytics, no crash reporting, no 'anonymous' statistics. There is no code in the project that sends anything outward."
          />
          <Fact
            title="No API keys"
            body="The repository is public and contains no credentials, and has nowhere to put one, because the model is local. That is a property of the design, not a policy someone has to remember."
          />
          <Fact
            title="Loopback only"
            body="Warden's internal server binds to 127.0.0.1. It is not reachable from your network, let alone the internet, even while it is running."
          />
        </div>
      </Section>

      <Callout title="The model is local because it has to be">
        <p>
          Warden reasons with a language model that runs on your processor. That is a
          functional requirement before it is a privacy one:{" "}
          <strong className="text-ink">
            a diagnostician that needs the internet to explain why you have no internet is
            not a diagnostician.
          </strong>{" "}
          The privacy consequence, that your machine&rsquo;s configuration never leaves it,
          comes free with getting the engineering right.
        </p>
      </Callout>

      <Section
        title="What it is capable of doing"
        blurb="The honest way to describe the risk of a tool like this is not 'it is safe', but 'here is the complete set of things it can do'."
      >
        <Prose>
          <p>
            Warden can run seventeen commands. Not seventeen kinds of command: seventeen specific
            ones, written by hand, sitting in the source where you can read them before you
            install anything. The AI selects from that list; it cannot compose, extend or edit
            it.
          </p>
          <p>
            Commands are passed to Windows as separate arguments rather than a line of text
            given to a shell. There is no shell anywhere in the execution path, so there is
            nothing for a crafted network name or device path to inject into.
          </p>
          <p>
            Nothing runs without you pressing a button. Not on a timer, not as a default, not
            in the background, and not in bulk. There is no &ldquo;fix everything&rdquo;.
          </p>
        </Prose>
      </Section>

      <Section title="If something goes wrong anyway">
        <div className="space-y-2.5">
          <Fact
            title="A restore point before anything disruptive"
            body="Before the first disruptive action of a session, Warden asks Windows for a System Restore checkpoint. If System Protection is switched off it says so rather than pretending a safety net exists."
          />
          <Fact
            title="Warden does not roll your machine back itself"
            body="It opens Windows' own restore screen. Undoing system state reverts changes Warden never made and cannot verify, and doing that silently from inside the tool you already suspect would be the wrong instinct."
          />
          <Fact
            title="Everything it did is written down"
            body="Each run records what was read, what was concluded, what you approved and whether it worked, including the times it did not. It is a file on your disk, in a format you can read."
          />
        </div>
      </Section>

      <Section title="Verify any of this">
        <Prose>
          <p>
            None of the above should be taken on trust, which is why the whole thing is open.
            The claim &ldquo;it sends nothing&rdquo; is checkable in an afternoon: there is one
            HTTP client in the project and it points at{" "}
            <code className="rounded bg-sunken px-1.5 py-0.5 font-mono text-[12px]">
              127.0.0.1
            </code>
            .
          </p>
        </Prose>
        <a
          href={REPO}
          className="mt-3 inline-block text-[14px] font-medium text-series-1 hover:underline"
        >
          Read the source on GitHub →
        </a>
      </Section>

      <Section title="Reporting a problem">
        <Prose>
          <p>
            If you find a security issue, please open an issue on GitHub. This is a student
            project without a formal disclosure process, but a real problem will be taken
            seriously and fixed in the open.
          </p>
        </Prose>
      </Section>
    </PageShell>
  );
}

function Fact({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface p-4">
      <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{body}</p>
    </div>
  );
}
