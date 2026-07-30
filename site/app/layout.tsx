import type { Metadata } from "next";
import "./globals.css";
import { Footer, Header } from "@/components/chrome";

export const metadata: Metadata = {
  metadataBase: new URL("https://warden.vercel.app"),
  title: {
    default: "Warden: the Windows troubleshooter that shows its work",
    template: "%s · Warden",
  },
  description:
    "Warden reads your actual machine, works out what is wrong, shows you the evidence, "
    + "and runs nothing without your permission. Then it re-measures to check the fix worked.",
  keywords: ["windows troubleshooter", "pc diagnostics", "local ai", "system repair"],
  openGraph: {
    title: "Warden: the Windows troubleshooter that shows its work",
    description:
      "Reads your machine, proposes one specific fix with the readings that justify it, "
      + "asks first, then re-measures to prove it worked.",
    type: "website",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="flex min-h-full flex-col antialiased">
        <Header />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
