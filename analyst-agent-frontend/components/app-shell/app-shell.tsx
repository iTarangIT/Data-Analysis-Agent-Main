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
