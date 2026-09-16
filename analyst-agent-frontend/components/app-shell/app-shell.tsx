import type { Thread, User } from "@/lib/api/types";

import { MobileBar } from "./mobile-bar";
import { Sidebar } from "./sidebar";
import { SidebarProvider } from "./sidebar-context";

/**
 * The chrome. One sidebar holding navigation and every conversation, and the page beside it.
 *
 * This used to be a top rail, on the argument that a navigation column would steal
 * horizontal room from a result table that can be five hundred columns wide. The column
 * folds to a rail and the main column carries `min-w-0`, so the table keeps its own internal
 * scroll instead of forcing the flex row wider than the viewport. That is what makes the
 * column affordable; without `min-w-0` the old objection would be exactly right.
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
 */
export function AppShell({
  user,
  threads = [],
  collapsed = false,
  children,
}: {
  user: User | null;
  threads?: Thread[];
  collapsed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <SidebarProvider defaultCollapsed={collapsed}>
      <div data-app-shell className="flex h-dvh overflow-hidden bg-surface">
        <Sidebar user={user} threads={threads} />

        {/* `min-w-0` is what stops a wide result table from stretching this flex row past the
            viewport; without it the table would push the sidebar off screen instead of
            scrolling inside its own box. */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <MobileBar />
          {children}
        </div>
      </div>
    </SidebarProvider>
  );
}
