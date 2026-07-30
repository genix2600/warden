import type { Metadata } from "next";
import { Callout, Code, CommandBlock, PageShell, Prose, Section } from "@/components/ui";
import {
  DOWNLOAD_URL,
  INSTALLER_SIZE,
  MODEL_SIZE,
  OFFLINE_SIZE,
  OFFLINE_URL,
  REPO,
  VERSION,
  ZIP_URL,
} from "@/lib/product";

export const metadata: Metadata = {
  title: "Download",
  description:
    "Warden for Windows 10 and 11. One small installer, no account. The AI runs on "
    + "your own machine.",
};

export default function DownloadPage() {
  return (
    <PageShell
      eyebrow={`Version ${VERSION}`}
      title="Download Warden"
      lead="Windows 10 or 11, 64-bit. No account, and nothing to configure. The AI runs on your own processor, so once it is set up nothing you look at leaves the machine."
    >
      <section>
        <a
          href={DOWNLOAD_URL}
          className="inline-block rounded-xl bg-series-1 px-6 py-3.5 text-[16px] font-semibold text-white transition-opacity hover:opacity-90"
        >
          Download for Windows · {INSTALLER_SIZE}
        </a>
        <p className="mt-3 text-[13px] text-muted">
          Installs to your user folder. It does not ask for administrator to install, and it
          does not need administrator to run.
        </p>

        <div className="mt-5 rounded-xl border border-hairline bg-surface p-4">
          <h2 className="text-[14px] font-semibold text-ink">
            No reliable internet on the machine you are installing to?
          </h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
            The standard download fetches the AI model on request, the first time you ask
            for it — about {MODEL_SIZE}, kept afterwards. If that machine will never have a
            usable connection, take the offline edition instead: same software, with the
            model already inside it.
          </p>
          <a
            href={OFFLINE_URL}
            className="mt-2.5 inline-block text-[13px] font-medium text-series-1 hover:underline"
          >
            Download the offline edition · {OFFLINE_SIZE} →
          </a>
        </div>
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

      <Section title="About the AI model">
        <Prose>
          <p>
            Warden reasons with a language model that runs on your own processor. It is not
            in the installer, because bundling it would make this a one-gigabyte download
            and most people would never find out whether the software was any good.
          </p>
          <p>
            Instead the first launch works immediately using the built-in rules engine —
            which handles every scenario end to end — and the Readiness page offers to fetch
            the model when you want it. About {MODEL_SIZE}, downloaded once, kept in your
            user folder, and used offline from then on.
          </p>
          <p>
            Nothing is downloaded without you asking. Warden does not spend a gigabyte of
            your bandwidth because you opened it.
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
          <PathRow
            path="%LOCALAPPDATA%\Warden\models"
            what="The AI model, once you ask for it. Kept outside the application folder so an upgrade does not mean downloading it again."
          />
        </div>
        <p className="mt-3 text-[13px] text-muted">
          Nothing is written outside your user folder, and nothing is sent anywhere.
        </p>
      </Section>

      <Section title="Requirements">
        <div className="grid gap-2 sm:grid-cols-2">
          <Requirement label="Windows" value="10 or 11, 64-bit (x64)" />
          <Requirement label="Disk" value="200 MB, plus 1 GB if you add the model" />
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
            You need Python 3.11+, Node 18+, and about ten minutes. The model runtime is
            staged separately because it is third-party binaries that do not belong in a git
            history; drop <Code>-RuntimeOnly</Code> to build the offline edition instead.
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
