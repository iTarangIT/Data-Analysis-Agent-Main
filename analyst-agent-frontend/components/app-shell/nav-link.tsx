"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * A row in the sidebar. The current section is a filled pill in the brand's soft tint,
 * which is the one place that tint is used, so "where am I" never has to compete with
 * anything else on the page for attention.
 *
 * `highlight={false}` is for "New chat": it points at /ask, but the conversation you are in
 * is marked in the chat list below it, and marking both would say the same thing twice.
 *
 * `icon` takes a rendered element rather than a component. The sidebar is a client component
 * today, but this row used to be rendered from a server one, and an element is the form that
 * crosses that boundary either way. Lucide's icons stroke with `currentColor`, so the pill
 * still tints them.
 */
export function NavLink({
  href,
  icon,
  highlight = true,
  onNavigate,
  children,
}: {
  href: string;
  icon?: React.ReactNode;
  highlight?: boolean;
  onNavigate?: () => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const active = highlight && (pathname === href || pathname.startsWith(`${href}/`));

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
        active
          ? "bg-brand-soft font-medium text-brand"
          : "text-ink hover:bg-surface-sunk",
      )}
    >
      {icon ? (
        <span
          aria-hidden
          className={cn(
            "flex size-4 shrink-0 items-center justify-center",
            !active && "text-ink-muted",
          )}
        >
          {icon}
        </span>
      ) : null}
      <span className="truncate">{children}</span>
    </Link>
  );
}

/** The same destination on the folded rail: the icon alone, named for assistive tech. */
export function RailLink({
  href,
  label,
  icon,
  highlight = true,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  highlight?: boolean;
}) {
  const pathname = usePathname();
  const active = highlight && (pathname === href || pathname.startsWith(`${href}/`));

  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex size-9 items-center justify-center rounded-lg transition-colors",
        active ? "bg-brand-soft text-brand" : "text-ink-muted hover:bg-surface-sunk hover:text-ink",
      )}
    >
      <span aria-hidden className="flex size-[1.125rem] items-center justify-center">
        {icon}
      </span>
    </Link>
  );
}
