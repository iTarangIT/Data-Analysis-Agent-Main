"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * A row in the sidebar. The current section is a filled pill in the brand's soft tint,
 * which is the one place that tint is used, so "where am I" never has to compete with
 * anything else on the page for attention.
 *
 * `icon` takes a rendered element rather than a component. The shell is a server component
 * and this is a client one, so a component reference would be a bare function crossing the
 * boundary, which React refuses to serialise. Lucide's icons carry no "use client" banner,
 * so they are not client references either -- rendering them on the server and sending the
 * SVG is the way across. They stroke with `currentColor`, so the pill still tints them.
 */
export function NavLink({
  href,
  icon,
  children,
}: {
  href: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
        active
          ? "bg-brand-soft font-medium text-brand"
          : "text-ink-muted hover:bg-surface-sunk hover:text-ink",
      )}
    >
      {icon ? (
        <span aria-hidden className="flex size-4 shrink-0 items-center justify-center">
          {icon}
        </span>
      ) : null}
      <span className="truncate">{children}</span>
    </Link>
  );
}
