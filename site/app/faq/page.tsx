import type { Metadata } from "next";
import Link from "next/link";
import { PageShell } from "@/components/ui";
import { REPO } from "@/lib/product";

export const metadata: Metadata = {
  title: "FAQ",
  description:
    "Does it need internet, does it send data anywhere, can it break my computer, and "
    + "why is the download so large.",
};

const FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: "Does it need an internet connection?",
    a: (
      <>
        Not to work. The reasoning happens on your own processor, so once Warden is set up
        it keeps working when the network is the thing that is broken. That matters,
        because a troubleshooter that needs the internet to explain why you have no internet
        is useless in the exact situation it is for.
        <br />
        <br />
        Two things do need a connection, and neither is required. Fetching the local AI
        model, once, if you want it, and there is an offline edition with it already inside
        for a machine that will never be online. And the optional cloud model, which is off
        until you enable it with your own API key and which, being hosted, is exactly no use
        for the fault above. Warden falls back to the local model automatically when it
        cannot be reached.
      </>
    ),
  },
  {
    q: "Does it send my data anywhere?",
    a: (
      <>
        Not by default, and not without you deciding to. There is no account, no telemetry
        and no crash reporting, and the internal server binds to{" "}
        <code className="font-mono text-[12px]">127.0.0.1</code> so it is not reachable from
        your network at all.
        <br />
        <br />
        The single exception is the cloud model, which is off on every install. Switch it on
        with your own API key and Warden sends that provider the symptom and the readings
        behind it when it answers a diagnosis. Not your files, not your browsing, and nothing
        Warden has not itself measured.{" "}
        <Link href="/security" className="text-series-1 hover:underline">
          More on the security page
        </Link>
        .
      </>
    ),
  },
  {
    q: "Can it break my computer?",
    a: (
      <>
        It runs seventeen specific commands, all reviewed and visible in the source, and
        none of them without you pressing a button first. Before anything disruptive it asks
        Windows for a System Restore point. If something still went wrong, it opens
        Windows&rsquo; own restore screen rather than trying to undo your system itself.
        <br />
        <br />
        The honest answer is that any tool with permission to change settings carries some
        risk. Warden&rsquo;s response is to show you the exact command first, keep the list
        short enough to read, and write down everything it did.
      </>
    ),
  },
  {
    q: "Why is the download so small for something with an AI in it?",
    a: (
      <>
        Because the model is not in it. The installer is about 46 MB; the model is roughly a
        gigabyte and is fetched separately, on request, from the Readiness page.
        <br />
        <br />
        Warden is useful before you do that. The rules engine handles every scenario end to
        end, and the interface tells you which one answered. Spending a gigabyte of your
        bandwidth because you opened an application is not a decision Warden makes for you.
      </>
    ),
  },
  {
    q: "Why does Windows warn me when I run it?",
    a: (
      <>
        The installer is not code-signed, because a certificate costs a few hundred dollars a
        year and this is a student project. SmartScreen warns about any unsigned installer.
        Choose <strong className="text-ink">More info</strong> then{" "}
        <strong className="text-ink">Run anyway</strong>. If that makes you uneasy, good
        instinct: the source is public and you can build it yourself instead.
      </>
    ),
  },
  {
    q: "Do I need to be an administrator?",
    a: (
      <>
        Not to install it, and not to run it. Some fixes do need administrator, such as restarting
        a device or a Windows service, and for those Warden says so and offers to restart itself
        with the rights it needs. Everything else works as a standard user.
      </>
    ),
  },
  {
    q: "What if the AI gets it wrong?",
    a: (
      <>
        Several things stop that mattering much. It can only choose from a fixed list, and only
        actions permitted for that specific problem. Its parameters are checked against what
        was actually measured. You see the command before it runs. And afterwards Warden
        re-measures. If the fix did not work, it says so and tries something else rather than
        declaring victory.
      </>
    ),
  },
  {
    q: "Does it work on Mac or Linux?",
    a: (
      <>
        No. Warden reads Windows-specific interfaces: WMI, the Windows event log, the registry,
        Windows services. There is no meaningful cross-platform version of what it does.
        Windows 10 and 11, 64-bit.
      </>
    ),
  },
  {
    q: "Will it slow my computer down?",
    a: (
      <>
        The monitoring is light, and samples a handful of Windows APIs on a timer. The local
        AI model only loads when there is something to reason about, and it will use your
        processor properly for those ten or twenty seconds. It is idle the rest of the time.
        The cloud model, if you enable it, uses none of your processor at all and answers in
        two to four seconds instead.
      </>
    ),
  },
  {
    q: "Is it really open source?",
    a: (
      <>
        Yes.{" "}
        <a href={REPO} className="text-series-1 hover:underline">
          Every line is on GitHub
        </a>
        , including the build scripts that produce the installer on this site. The claims on
        these pages are meant to be checkable, and that is the point of publishing it.
      </>
    ),
  },
];

export default function FaqPage() {
  return (
    <PageShell
      eyebrow="Questions"
      title="Reasonable things to ask before installing this"
      lead="Warden asks for a lot of access to your machine. These are the questions you should be asking, answered without marketing."
    >
      <section className="space-y-2.5">
        {FAQS.map((item) => (
          <details
            key={item.q}
            className="group rounded-xl border border-hairline bg-surface p-4 [&_summary::-webkit-details-marker]:hidden"
          >
            <summary className="flex cursor-pointer list-none items-center gap-3">
              <h2 className="flex-1 text-[15px] font-semibold text-ink">{item.q}</h2>
              <span
                aria-hidden
                className="shrink-0 text-muted transition-transform group-open:rotate-45"
              >
                +
              </span>
            </summary>
            <div className="mt-2.5 max-w-2xl text-[14px] leading-relaxed text-ink-2">
              {item.a}
            </div>
          </details>
        ))}
      </section>
    </PageShell>
  );
}
