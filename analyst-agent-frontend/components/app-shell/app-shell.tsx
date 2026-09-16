import Link from "next/link";
import { Database, LogOut, MessagesSquare, ScrollText } from "lucide-react";

import { logout } from "@/actions/auth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { initialsOf } from "@/lib/initials";
import type { User } from "@/lib/api/types";

import { NavLink } from "./nav-link";

/**
 * The chrome. A left rail, with every page rendered as cards on the ground beside it.
 *
 * This used to be a top rail, on the argument that a navigation column would steal
 * horizontal room from a result table that can be five hundred columns wide. The rail is
 * narrow and the main column carries `min-w-0`, so the table keeps its own internal scroll
 * instead of forcing the flex row wider than the viewport. That is what makes the column
 * affordable; without `min-w-0` the old objection would be exactly right.
 *
 * The root is `h-dvh overflow-hidden`, not `min-h-dvh`. A min-height gives the flex
 * container no definite main size, so a tall page would grow it rather than clip, and every
 * descendant `overflow-y-auto` -- including the one that pins the composer -- would quietly
 * stop working.
 *
 * `data-app-shell` is what globals.css keys the document's own `overflow: hidden` off. The
 * shell sizes itself to the viewport, but it cannot stop a sibling growing the page beneath
 * it, and `body` is a flex column that browser extensions append themselves to. See the note
 * on that rule.
 *
 * Icons are rendered here and passed down as elements. See the note in nav-link.tsx.
 */

const NAV = [
  { href: "/ask", label: "Ask", icon: <MessagesSquare className="size-4" strokeWidth={1.75} /> },
  { href: "/connections", label: "Connections", icon: <Database className="size-4" strokeWidth={1.75} /> },
  { href: "/runs", label: "Runs", icon: <ScrollText className="size-4" strokeWidth={1.75} /> },
];

export function AppShell({
  user,
  children,
}: {
  user: User | null;
  children: React.ReactNode;
}) {
  const wordmark = (
    <Link href="/ask" className="font-mono text-sm tracking-tight text-ink">
      analyst
    </Link>
  );

  const nav = NAV.map((item) => (
    <NavLink key={item.href} href={item.href} icon={item.icon}>
      {item.label}
    </NavLink>
  ));

  const signOut = (
    <form action={logout}>
      <Button
        type="submit"
        variant="ghost"
        size="icon-sm"
        aria-label="Sign out"
        title="Sign out"
        className="text-ink-muted hover:bg-surface-sunk hover:text-ink"
      >
        <LogOut aria-hidden className="size-4" strokeWidth={1.75} />
      </Button>
    </form>
  );

  return (
    <div data-app-shell className="flex h-dvh overflow-hidden bg-bg">
      <aside className="hidden w-[212px] shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex h-14 shrink-0 items-center px-5">{wordmark}</div>

        <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-2">
          {nav}
        </nav>

        {/* Role is deliberately absent: the agent hardcodes every account to `owner` and
            enforces nothing against it, so a badge here would be decoration pretending
            to be permission. */}
        <div className="shrink-0 border-t border-line p-3">
          <div className="flex items-center gap-2.5">
            {user ? (
              <>
                <Avatar className="size-8 shrink-0">
                  <AvatarFallback className="bg-brand-soft font-mono text-[0.6875rem] font-medium text-brand">
                    {initialsOf(user)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[0.8125rem] leading-tight font-medium text-ink">
                    {user.name?.trim() || user.email}
                  </p>
                  <p className="truncate text-xs leading-tight text-ink-muted">
                    {user.tenant_name}
                  </p>
                </div>
              </>
            ) : (
              <div className="flex-1" />
            )}
            {signOut}
          </div>
        </div>
      </aside>

      {/* `min-w-0` is what stops a wide result table from stretching this flex row past the
          viewport; without it the table would push the sidebar off screen instead of
          scrolling inside its own box. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-4 md:hidden">
          {wordmark}
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">{nav}</nav>
          {signOut}
        </header>

        {children}
      </div>
    </div>
  );
}
