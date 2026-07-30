import type { Metadata } from "next";
import Link from "next/link";
import { PageShell, Prose, Section } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "Privacy",
  description: "Warden collects nothing, transmits nothing, and stores everything locally.",
};

export default function PrivacyPage() {
  return (
    <PageShell
      eyebrow="Last updated 30 July 2026"
      title="Privacy"
      lead="This is short because there is very little to say. Warden does not collect anything."
    >
      <Section title="What the software collects">
        <Prose>
          <p>
            <strong className="text-ink">Nothing is transmitted.</strong> Warden reads a great
            deal about your computer — the Windows event log, installed services, device
            inventory, network configuration, drive health, temperatures — and all of it stays
            on the machine it was read from.
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
          <p>Two things, both inside your own user folder:</p>
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
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-ink-2">
          Both are ordinary files. You can read them, copy them, or delete them at any time,
          and uninstalling asks before removing them.
        </p>
      </Section>

      <Section title="The AI model">
        <Prose>
          <p>
            Warden&rsquo;s reasoning runs on a language model bundled with the download and
            executed on your processor. Your machine&rsquo;s configuration is never sent to a
            model provider, because there is no provider — no third-party AI service is
            involved at any point.
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
