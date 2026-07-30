import type { Metadata } from "next";
import { Callout, Code, CommandBlock, PageShell, Prose, Section } from "@/components/ui";
import { DOWNLOAD_URL, INSTALLER_SIZE, REPO, VERSION, ZIP_URL } from "@/lib/product";

export const metadata: Metadata = {
  title: "Download",
  description:
    "Warden for Windows 10 and 11. One installer, no account, no internet needed after "
    + "the download — the AI model is inside it.",
};

export default function DownloadPage() {
  return (
    <PageShell
      eyebrow={`Version ${VERSION}`}
      title="Download Warden"
      lead="Windows 10 or 11, 64-bit. No account, and nothing to configure. After the download it never needs the internet again."
    >
      <section>
        <a
          href={DOWNLOAD_URL}
          className="inline-block rounded-xl bg-series-1 px-6 py-3.5 text-[16px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Download the installer · {INSTALLER_SIZE}
        </a>
        <p className="mt-3 text-[13px] text-muted">
          Installs to your user folder. It does not ask for administrator to install, and it
          does not need administrator to run.
        </p>
      </section>

      <Callout tone="warning" title="Windows will warn you, and here is why">
        <p>
          The installer is not code-signed — a certificate costs a few hundred pounds a year
          and this is a student project. So SmartScreen will show{" "}
          <em>&ldquo;Windows protected your PC&rdquo;</em> the first time you run it. Choose{" "}
          <strong className="text-ink">More info</strong>, then{" "}
          <strong className="text-ink">Run anyway</strong>.
        </p>
        <p className="mt-2">
          You should be suspicious of that prompt in general. The reason to trust this one is
          that <a href={REPO} className="text-series-1 hover:underline">every line of the
          source is public</a> and the build script that produces this file is in the
          repository.
        </p>
      </Callout>

      <Section title="Why it is nearly a gigabyte">
        <Prose>
          <p>
            Because the AI model is inside it. Warden reasons about your machine with a
            language model that runs locally, and bundling it means the download works on a
            computer that has never installed anything — and keeps working when the network
            is the thing that is broken.
          </p>
          <p>
            The alternative would be a 45 MB download that fetches a model on first run, which
            fails in exactly the situation Warden is for.
          </p>
        </Prose>
      </Section>

      <Section title="What it puts on your machine">
        <div className="space-y-2.5">
          <PathRow
            path="%LOCALAPPDATA%\Programs\Warden"
            what="The application itself. Removed completely when you uninstall."
          />
          <PathRow
            path="%LOCALAPPDATA%\Warden\sessions"
            what="A record of what Warden saw and did, one file per run, so a decision can be reopened later. Uninstall asks before deleting these."
          />
          <PathRow
            path="%LOCALAPPDATA%\Warden\logs"
            what="Plain-text log. The first place to look if something misbehaves."
          />
        </div>
        <p className="mt-3 text-[13px] text-muted">
          Nothing is written outside your user folder, and nothing is sent anywhere.
        </p>
      </Section>

      <Section title="Requirements">
        <div className="grid gap-2 sm:grid-cols-2">
          <Requirement label="Windows" value="10 or 11, 64-bit (x64)" />
          <Requirement label="Disk" value="About 1.2 GB once installed" />
          <Requirement label="Memory" value="4 GB, 8 GB comfortably" />
          <Requirement label="Graphics" value="None needed — it runs on the processor" />
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-muted">
          Warden also needs the Microsoft Edge WebView2 Runtime to draw its window. Windows 11
          has it already, and so does almost every up-to-date Windows 10 machine. The installer
          checks and tells you before installing if it is missing.
        </p>
      </Section>

      <Section
        title="If your machine blocks installers"
        blurb="Some managed laptops will not run a setup program. The plain folder works instead."
      >
        <a href={ZIP_URL} className="text-[14px] font-medium text-series-1 hover:underline">
          Download the zip instead →
        </a>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
          Extract it anywhere and run <Code>Warden.exe</Code> from inside the folder. Keep the
          folder together — the <Code>_internal</Code> directory beside the executable is not
          optional.
        </p>
      </Section>

      <Section title="Or build it yourself">
        <Prose>
          <p>
            You need Python 3.11+, Node 18+, and about ten minutes. The model runtime is staged
            separately because it is a gigabyte of third-party binaries that do not belong in a
            git history.
          </p>
        </Prose>
        <div className="mt-3">
          <CommandBlock>
            {`git clone ${REPO}\ncd warden\n.\\scripts\\fetch-model.ps1      # stages the local model\n.\\scripts\\build-installer.ps1  # produces dist\\Warden-Setup-${VERSION}.exe`}
          </CommandBlock>
        </div>
      </Section>
    </PageShell>
  );
}

function PathRow({ path, what }: { path: string; what: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface p-3.5">
      <code className="font-mono text-[12px] text-series-1">{path}</code>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{what}</p>
    </div>
  );
}

function Requirement({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-[13px] text-ink">{value}</div>
    </div>
  );
}
