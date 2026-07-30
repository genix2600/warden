import type { Metadata } from "next";
import { PageShell, Prose, Section } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "Terms",
  description: "Warden is free, open-source software provided as-is, with no warranty.",
};

export default function TermsPage() {
  return (
    <PageShell
      eyebrow="Last updated 30 July 2026"
      title="Terms of use"
      lead="Warden is free, open-source software from a student project. There is no company, no contract and no charge."
    >
      <Section title="The licence">
        <Prose>
          <p>
            Warden is released under the licence in the repository, and that licence — not this
            page — is what governs your use of the software. This page is a plain-English
            summary of what it means in practice.
          </p>
          <p>
            You may use it, read it, modify it and share it. It costs nothing and there is
            nothing to agree to before installing.
          </p>
        </Prose>
        <a
          href={`${REPO}/blob/main/LICENSE`}
          className="mt-3 inline-block text-[14px] font-medium text-series-1 hover:underline"
        >
          Read the licence →
        </a>
      </Section>

      <Section title="No warranty">
        <Prose>
          <p>
            The software is provided <strong className="text-ink">as is</strong>, without
            warranty of any kind. It is a student project, tested primarily on the machines its
            authors own. It may not work on yours.
          </p>
          <p>
            Warden changes Windows settings when you approve it to. Those changes are real, and
            you are responsible for deciding whether to allow them. The design tries hard to
            make that decision an informed one — you see the exact command, its effect, and the
            test that will judge it, before anything runs — but the decision remains yours.
          </p>
        </Prose>
      </Section>

      <Section title="What you should do anyway">
        <Prose>
          <p>
            Keep backups of anything you care about. This is true regardless of Warden, but it
            is worth saying on a page about a tool that modifies system settings.
          </p>
          <p>
            Warden asks Windows for a System Restore point before the first disruptive action
            of a session. That is a useful safety net and not a substitute for a backup.
          </p>
        </Prose>
      </Section>

      <Section title="Nothing is for sale">
        <Prose>
          <p>
            There is no paid tier, no subscription and no payment processing anywhere in this
            project. The tiers shown on the pricing page are illustrative and clearly marked as
            such. If that ever changes, these terms will change with it, in public.
          </p>
        </Prose>
      </Section>

      <Section title="Third-party components">
        <Prose>
          <p>
            The download bundles a local model runtime and model weights, both redistributed
            unmodified under their own open-source licences. Those licences ship inside the
            application folder, and the build script that assembles them is in the repository.
          </p>
        </Prose>
      </Section>
    </PageShell>
  );
}
