import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

// One superfamily, drawn for technical contexts. Mono is not decoration here: it carries the
// SQL and the table cells, which genuinely are monospace content.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Analyst",
  description: "Ask your database a question in plain English and watch it answer.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} h-full`}>
      {/* Extensions inject attributes onto body before React hydrates, which is not a
          mismatch we can fix or should report. */}
      <body className="flex min-h-full flex-col" suppressHydrationWarning>
        {children}
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
