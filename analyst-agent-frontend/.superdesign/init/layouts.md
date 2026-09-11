# Shared Layouts

The app has **no sidebar**. The shell is a 3.5rem (`h-14`) top rail. The reason is
recorded in `app-shell.tsx`: a nav column would steal horizontal room from a result
table that can run to hundreds of columns.

Nesting:

```
app/layout.tsx                 fonts (IBM Plex Sans + Mono) + <Toaster>
├── app/(app)/layout.tsx       requireSession() -> <AppShell>
│     └── /ask  /connections  /runs
└── app/(auth)/layout.tsx      split hero | form grid, hero hidden below lg
      └── /login  /register
```

Active-nav treatment is an **underline**, not a filled pill (`nav-link.tsx`).

`.on-ground` is the dark-chrome class. It is applied in exactly two places in the
whole codebase: the shell header (`app-shell.tsx`) and the auth hero (`auth-hero.tsx`).
It re-points the shadcn primitive variables at the dark palette rather than defining a
second palette.

---

## `app/layout.tsx`

```tsx
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
```

## `app/(app)/layout.tsx`

```tsx
import { AppShell } from "@/components/app-shell/app-shell";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // proxy.ts already made an optimistic check, but it reads a cookie and nothing more. This
  // is the gate that actually holds.
  await requireSession();
  const user = await getCurrentUser();

  return <AppShell user={user}>{children}</AppShell>;
}
```

## `app/(auth)/layout.tsx`

```tsx
import { AuthHero } from "@/components/auth/auth-hero";

/**
 * Split. The hero holds the ground; the form sits on paper, which is the same division the
 * rest of the app uses: the machine's side is dark, and what you work with is printed.
 *
 * Below the large breakpoint the hero is dropped rather than stacked. It is an argument, not
 * information, and on a phone it would only push the form off the screen.
 */
export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <AuthHero />
      <main className="flex items-center justify-center bg-paper px-5 py-12 sm:px-8">
        <div className="w-full max-w-[26rem]">{children}</div>
      </main>
    </div>
  );
}
```

## `components/app-shell/app-shell.tsx`

```tsx
import Link from "next/link";

import { logout } from "@/actions/auth";
import { Button } from "@/components/ui/button";
import type { User } from "@/lib/api/types";

import { NavLink } from "./nav-link";

/**
 * The chrome. Everything here sits on ground; pages put their artifacts on paper.
 *
 * A single top rail rather than a sidebar: this app has three places to be, and a column of
 * navigation would take horizontal room from the one thing that needs it, which is a table
 * that can be five hundred rows wide.
 */
export function AppShell({
  user,
  children,
}: {
  user: User | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-dvh flex-col bg-ground">
      <header className="on-ground flex h-14 shrink-0 items-center gap-6 border-b border-rule-ground px-5">
        <Link
          href="/ask"
          className="font-mono text-sm tracking-tight text-ground-ink hover:text-ground-ink"
        >
          analyst
        </Link>

        <nav className="flex items-center gap-1">
          <NavLink href="/ask">Ask</NavLink>
          <NavLink href="/connections">Connections</NavLink>
          <NavLink href="/runs">History</NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          {user ? (
            <span className="hidden text-[0.8125rem] text-ground-muted sm:inline">
              {user.tenant_name}
            </span>
          ) : null}
          <form action={logout}>
            <Button
              type="submit"
              variant="ghost"
              className="h-8 px-2 text-[0.8125rem] text-ground-muted hover:bg-ground-raised hover:text-ground-ink"
            >
              Sign out
            </Button>
          </form>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
```

## `components/app-shell/nav-link.tsx`

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** The current section is marked by an underline rather than a filled pill, so the rail stays quiet. */
export function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-sm px-2.5 py-1.5 text-[0.8125rem] transition-colors",
        active
          ? "text-ground-ink underline decoration-ground-muted underline-offset-[6px]"
          : "text-ground-muted hover:text-ground-ink",
      )}
    >
      {children}
    </Link>
  );
}
```

## `components/auth/auth-hero.tsx`

```tsx
/**
 * The sign-in hero.
 *
 * One English question, a rule, and the SQL it became. That translation is the product, so it
 * is the thing the page opens with, set at nearly the same optical size in the two faces of
 * one superfamily. No marketing copy, no feature list, no gradient: the demonstration is the
 * argument.
 */

const QUESTION = "Which customers bought the most batteries last quarter?";

// Kept inside about fifty characters a line so the panel never needs a scrollbar. A
// horizontal scrollbar under the hero would undercut the claim that this is the finished
// article.
const SQL = [
  ["SELECT", " c.name, SUM(oi.quantity) AS units"],
  ["FROM", " orders o"],
  ["JOIN", " order_items oi ON oi.order_id = o.id"],
  ["JOIN", " customers c ON c.id = o.customer_id"],
  ["WHERE", " o.placed_at >= date_trunc('quarter', now())"],
  ["GROUP BY", " 1"],
  ["ORDER BY", " 2 DESC"],
  ["LIMIT", " 500"],
] as const;

export function AuthHero() {
  return (
    <div className="on-ground hidden flex-col justify-between gap-10 overflow-y-auto bg-ground p-10 lg:flex lg:p-14">
      <p className="font-mono text-sm tracking-tight text-ground-muted">analyst</p>

      <div className="max-w-[46ch]">
        <p className="text-[1.75rem] leading-[1.25] font-normal text-ground-ink">{QUESTION}</p>

        <div className="my-7 h-px w-full bg-rule-ground" />

        <pre className="font-mono text-[0.9375rem] leading-[1.7] text-ground-ink">
          <code>
            {SQL.map(([keyword, rest], i) => (
              // Keyed by position: two lines here begin with JOIN.
              <span key={i} className="block">
                <span className="text-ground-muted">{keyword}</span>
                {rest}
              </span>
            ))}
          </code>
        </pre>
      </div>

      <p className="max-w-[42ch] text-sm leading-relaxed text-ground-muted">
        Every query is checked before it runs, and it only ever reads. You see the SQL, the rows
        it returned, and the answer.
      </p>
    </div>
  );
}
```
