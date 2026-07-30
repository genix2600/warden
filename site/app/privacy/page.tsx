import type { Metadata } from "next";
import Link from "next/link";
import { PageShell, Prose, Section } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "Warden collects nothing and stores everything locally. It transmits nothing "
    + "unless you switch on the optional cloud model, and this page says what that sends.",
};

export default function PrivacyPage() {
  return (
    <PageShell
      eyebrow="Last updated 30 July 2026"
      title="Privacy"
      lead="This is short because there is very little to say. Warden does not collect anything, and sends nothing anywhere unless you switch on the cloud model yourself."
    >
      <Section title="What the software collects">
        <Prose>
          <p>
            <strong className="text-ink">Nothing is collected.</strong> Warden reads a great
            deal about your computer: the Windows event log, installed services, device
            inventory, network configuration, drive health, temperatures. All of it stays on
            the machine it was read from, and none of it comes to us. There is no us: no
            server, nowhere for it to go.
          </p>
          <p>
            <strong className="text-ink">One exception, and it is off by default.</strong> If
            you switch on the cloud model and supply your own API key, then when it answers a
            diagnosis Warden sends that provider the symptom, the readings relevant to it,
            your Windows version, and the list of actions it may choose from. Not your files,
            not your browsing, not your account names, and nothing Warden has not itself
            measured. Their terms govern what happens to it after that, which is a real cost
            and the reason it is a choice rather than a default.
          </p>
          <p>
            There is no account, no licence key, no activation, no usage analytics and no crash
            reporting. No identifier for you or your machine is generated, because none is
            needed.
          </p>
        </Prose>
      </Section>

      <Section title="What is stored, and where">
        <Prose>
          <p>All inside your own user folder:</p>
        </Prose>
        <div className="mt-3 space-y-2">
          <Row
            path="%LOCALAPPDATA%\Warden\sessions"
            what="A record of each run: what was read, what was concluded, what you approved, and whether it worked. Kept so a decision can be reopened later. Never uploaded."
          />
          <Row
            path="%LOCALAPPDATA%\Warden\logs"
            what="A plain-text log of the application's own activity."
          />
          <Row
            path="%LOCALAPPDATA%\Warden\credentials.json"
            what="Only exists if you enabled the cloud model. Holds the API key you supplied and nothing else. Deleting the file switches cloud mode off."
          />
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-ink-2">
          Both are ordinary files. You can read them, copy them, or delete them at any time,
          and uninstalling asks before removing them.
        </p>
      </Section>

      <Section title="The AI model">
        <Prose>
          <p>
            By default, Warden&rsquo;s reasoning runs on a language model bundled with the
            download and executed on your processor. In that mode your machine&rsquo;s
            configuration is never sent to a model provider, because no provider is involved
            at any point.
          </p>
          <p>
            You can switch that for a hosted model, from the Model page inside the app, using
            an API key you obtain yourself. Doing so is the only circumstance in which
            anything Warden reads leaves your computer. It is off until you turn it on, the
            app states what is sent before it asks for the key, and every diagnosis is
            labelled with which model answered it.
          </p>
          <p>
            Your key is stored in{" "}
            <code>%LOCALAPPDATA%\Warden\credentials.json</code>, separately from your
            settings, and no part of the application returns it once saved.
          </p>
        </Prose>
      </Section>

      <Section title="This website">
        <Prose>
          <p>
            This site is static and carries no analytics, no advertising and no tracking
            cookies. It is hosted on Vercel, which keeps standard server logs including IP
            addresses, as any web host does. The download link points to GitHub, which counts
            release downloads.
          </p>
        </Prose>
      </Section>

      <Section title="Verifying this">
        <Prose>
          <p>
            A privacy policy is a promise, and promises are worth what the person making them
            is worth. This one is checkable instead: the source is public, there is exactly one
            HTTP client in the project, and it points at your own machine.
          </p>
        </Prose>
        <a
          href={REPO}
          className="mt-3 inline-block text-[14px] font-medium text-series-1 hover:underline"
        >
          Check for yourself →
        </a>
      </Section>

      <Section title="Contact">
        <Prose>
          <p>
            Warden is a student project with no company behind it. Questions and corrections
            belong in a GitHub issue, where the answer is public too. See also the{" "}
            <Link href="/security" className="text-series-1 hover:underline">
              security page
            </Link>
            .
          </p>
        </Prose>
      </Section>
    </PageShell>
  );
}

function Row({ path, what }: { path: string; what: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface p-3.5">
      <code className="font-mono text-[12px] text-series-1">{path}</code>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{what}</p>
    </div>
  );
}
