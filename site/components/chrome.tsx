"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { DOWNLOAD_URL, REPO } from "@/lib/product";

const NAV = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/what-it-covers", label: "What it covers" },
  { href: "/security", label: "Security" },
  { href: "/pricing", label: "Pricing" },
  { href: "/faq", label: "FAQ" },
] as const;

export function Header() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-hairline bg-plane/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-5 py-3">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <Shield />
          <span className="text-[15px] font-bold tracking-tight text-ink">Warden</span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href ? "page" : undefined}
              className={`rounded-lg px-2.5 py-1.5 text-[13px] transition-colors ${
                pathname === item.href
                  ? "bg-raised text-ink"
                  : "text-ink-2 hover:bg-raised/60 hover:text-ink"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <a
            href={REPO}
            className="hidden rounded-lg px-2.5 py-1.5 text-[13px] text-ink-2 transition-colors hover:text-ink sm:block"
          >
            Source
          </a>
          <a
            href={DOWNLOAD_URL}
            className="rounded-lg bg-series-1 px-3.5 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          >
            Download
          </a>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-label="Menu"
            aria-expanded={open}
            className="rounded-lg border border-hairline p-1.5 text-ink-2 md:hidden"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              {open ? <path d="M18 6 6 18M6 6l12 12" /> : <path d="M3 12h18M3 6h18M3 18h18" />}
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-hairline px-5 py-2 md:hidden">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="block rounded-lg px-2.5 py-2 text-[14px] text-ink-2 hover:bg-raised hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-hairline bg-sunken">
      <div className="mx-auto max-w-6xl px-5 py-10">
        <div className="flex flex-wrap gap-10">
          <div className="min-w-[240px] flex-1">
            <div className="flex items-center gap-2">
              <Shield />
              <span className="text-[14px] font-bold text-ink">Warden</span>
            </div>
            <p className="mt-2 max-w-sm text-[12px] leading-relaxed text-muted">
              An agentic Windows diagnostician that reads your machine, shows its evidence,
              and runs nothing without your say-so.
            </p>
          </div>

          <FooterColumn
            title="Product"
            links={[
              { href: "/how-it-works", label: "How it works" },
              { href: "/what-it-covers", label: "What it covers" },
              { href: "/download", label: "Download" },
              { href: "/pricing", label: "Pricing" },
            ]}
          />
          <FooterColumn
            title="Trust"
            links={[
              { href: "/security", label: "Security & privacy" },
              { href: "/faq", label: "FAQ" },
              { href: REPO, label: "Source code" },
            ]}
          />
          <FooterColumn
            title="Legal"
            links={[
              { href: "/privacy", label: "Privacy" },
              { href: "/terms", label: "Terms" },
              { href: `${REPO}/blob/main/LICENSE`, label: "Licence" },
            ]}
          />
        </div>

        <p className="mt-8 border-t border-hairline pt-5 text-[11px] leading-relaxed text-muted">
          Warden is a student project built for the ShriTeq 2026 hackathon. It runs on your
          machine and sends nothing anywhere unless you switch on the optional cloud
          model. Windows 10 and 11, x64.
        </p>
      </div>
    </footer>
  );
}

function FooterColumn({
  title,
  links,
}: {
  title: string;
  links: { href: string; label: string }[];
}) {
  return (
    <div>
      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h2>
      <ul className="mt-2.5 space-y-1.5">
        {links.map((link) => (
          <li key={link.href + link.label}>
            <Link
              href={link.href}
              className="text-[13px] text-ink-2 transition-colors hover:text-ink"
            >
              {link.label}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* The real mark, the same file Windows uses for the taskbar icon -- Next
   serves app/icon.png from /icon.png and generates the favicon from it. */
function Shield() {
  return (
    <Image src="/icon.png" alt="" aria-hidden width={18} height={18} priority />
  );
}
