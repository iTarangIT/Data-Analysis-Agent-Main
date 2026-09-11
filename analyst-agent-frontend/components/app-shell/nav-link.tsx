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
