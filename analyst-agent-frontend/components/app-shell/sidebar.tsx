"use client";

import {
  Database,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  SquarePen,
  X,
} from "lucide-react";
import Link from "next/link";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Suspense, useRef } from "react";

import { logout } from "@/actions/auth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Thread, User } from "@/lib/api/types";
import { initialsOf } from "@/lib/initials";
import { cn } from "@/lib/utils";

import { NavLink, RailLink } from "./nav-link";
import { useSidebar } from "./sidebar-context";
import { ThreadList } from "./thread-list";

/**
 * Who the account menu names: the agent's account when it answered, otherwise only what the
 * sign-in itself says, so an agent that is asleep does not leave the menu reading "?".
 */
export type Account = Pick<User, "name" | "email"> & { tenant_name: string | null };

/**
 * The one sidebar: new chat, the two other sections, every conversation, and the account.
 *
 * Three presentations of the same content. On desktop it is either the full column or, folded,
 * a rail of icons; below `md` it is a drawer over the page. The drawer closes itself when you
 * follow a link in it, because on a phone the page you asked for is underneath it.
 */
export function Sidebar({ user, threads }: { user: Account | null; threads: Thread[] }) {
  const { collapsed, toggleCollapsed, drawerOpen, setDrawerOpen } = useSidebar();

  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-line bg-bg md:flex",
          collapsed ? "w-[3.75rem]" : "w-[16.25rem]",
        )}
      >
        {collapsed ? (
          <Rail user={user} onExpand={toggleCollapsed} />
        ) : (
          <Column
            user={user}
            threads={threads}
            closeLabel="Close sidebar"
            closeIcon={<PanelLeftClose className="size-[1.125rem]" strokeWidth={1.75} />}
            onClose={toggleCollapsed}
          />
        )}
      </aside>

      <DialogPrimitive.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink-faint/40data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 md:hidden" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-50 flex w-[17.5rem] max-w-[85vw] flex-col bg-bg shadow-card data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:animate-in data-[state=open]:slide-in-from-left md:hidden"
          >
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <Column
              user={user}
              threads={threads}
              closeLabel="Close menu"
              closeIcon={<X className="size-[1.125rem]" strokeWidth={1.75} />}
              onClose={() => setDrawerOpen(false)}
              onNavigate={() => setDrawerOpen(false)}
            />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </>
  );
}

function Wordmark({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      href="/ask"
      onClick={onNavigate}
      className="rounded-md px-2 py-1 font-mono text-sm tracking-tight text-ink"
    >
      analyst
    </Link>
  );
}

function Column({
  user,
  threads,
  closeLabel,
  closeIcon,
  onClose,
  onNavigate,
}: {
  user: Account | null;
  threads: Thread[];
  closeLabel: string;
  closeIcon: React.ReactNode;
  onClose: () => void;
  onNavigate?: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between pr-2 pl-2.5">
        <Wordmark onNavigate={onNavigate} />
        <button
          type="button"
          onClick={onClose}
          aria-label={closeLabel}
          title={closeLabel}
          className="flex size-9 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink"
        >
          {closeIcon}
        </button>
      </div>

      <nav className="flex shrink-0 flex-col gap-px px-2">
        <NavLink
          href="/ask"
          highlight={false}
          onNavigate={onNavigate}
          icon={<SquarePen className="size-4" strokeWidth={1.75} />}
        >
          New chat
        </NavLink>
        <NavLink
          href="/connections"
          onNavigate={onNavigate}
          icon={<Database className="size-4" strokeWidth={1.75} />}
        >
          Connections
        </NavLink>
        <NavLink
          href="/runs"
          onNavigate={onNavigate}
          icon={<ScrollText className="size-4" strokeWidth={1.75} />}
        >
          Runs
        </NavLink>
      </nav>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {/* useSearchParams reads the URL, which a prerendered shell would not have. */}
        <Suspense fallback={null}>
          <ThreadList initial={threads} onNavigate={onNavigate} />
        </Suspense>
      </div>

      <div className="shrink-0 border-t border-line p-2">
        <AccountMenu user={user} />
      </div>
    </div>
  );
}

function Rail({ user, onExpand }: { user: Account | null; onExpand: () => void }) {
  return (
    <div className="flex h-full flex-col items-center gap-1 py-2.5">
      <button
        type="button"
        onClick={onExpand}
        aria-label="Open sidebar"
        title="Open sidebar"
        className="mb-2 flex size-9 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink"
      >
        <PanelLeftOpen aria-hidden className="size-[1.125rem]" strokeWidth={1.75} />
      </button>
      <RailLink
        href="/ask"
        label="New chat"
        highlight={false}
        icon={<SquarePen className="size-[1.125rem]" strokeWidth={1.75} />}
      />
      <RailLink
        href="/connections"
        label="Connections"
        icon={<Database className="size-[1.125rem]" strokeWidth={1.75} />}
      />
      <RailLink
        href="/runs"
        label="Runs"
        icon={<ScrollText className="size-[1.125rem]" strokeWidth={1.75} />}
      />
      <div className="mt-auto">
        <AccountMenu user={user} compact />
      </div>
    </div>
  );
}

/**
 * The account row, and sign-out behind it.
 *
 * Role is deliberately absent: the agent hardcodes every account to `owner` and enforces
 * nothing against it, so a badge here would be decoration pretending to be permission.
 *
 * Sign-out stays a form posting to the server action, so it works the same as it always did;
 * the menu item only submits it. The form sits outside the menu because the menu's content is
 * portalled away and unmounted when it closes.
 */
function AccountMenu({ user, compact = false }: { user: Account | null; compact?: boolean }) {
  const form = useRef<HTMLFormElement>(null);
  const name = user ? user.name?.trim() || user.email : "Account";

  return (
    <>
      <form ref={form} action={logout} className="hidden" />
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={compact ? `Account: ${name}` : undefined}
          title={compact ? name : undefined}
          className={cn(
            "flex items-center gap-2.5 rounded-lg text-left transition-colors hover:bg-surface-sunk data-[state=open]:bg-surface-sunk",
            compact ? "size-9 justify-center" : "w-full px-2 py-1.5",
          )}
        >
          <Avatar className={compact ? "size-7" : "size-8"}>
            <AvatarFallback className="bg-brand-soft font-mono text-[0.6875rem] font-medium text-brand">
              {initialsOf(user)}
            </AvatarFallback>
          </Avatar>
          {compact ? null : (
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[0.8125rem] leading-tight font-medium text-ink">
                {name}
              </span>
              {user?.tenant_name ? (
                <span className="block truncate text-xs leading-tight text-ink-muted">
                  {user.tenant_name}
                </span>
              ) : null}
            </span>
          )}
        </DropdownMenuTrigger>

        <DropdownMenuContent
          side={compact ? "right" : "top"}
          align={compact ? "end" : "start"}
          className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-xl p-1.5"
        >
          {user ? (
            <>
              <DropdownMenuLabel className="truncate text-xs font-normal text-ink-muted">
                {user.email}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
            </>
          ) : null}
          <DropdownMenuItem
            onSelect={() => form.current?.requestSubmit()}
            className="rounded-lg px-2.5 py-2"
          >
            <LogOut aria-hidden strokeWidth={1.75} />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
