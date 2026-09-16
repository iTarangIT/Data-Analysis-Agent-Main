"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SidebarTrigger } from "./sidebar-context";

/**
 * The top bar below `md`, where the sidebar is a drawer and something has to open it.
 *
 * Not on the ask screen: that screen already has a bar of its own for the database picker,
 * and puts the drawer's button in it, so a phone does not spend two rows on chrome.
 */
export function MobileBar() {
  const pathname = usePathname();
  if (pathname === "/ask" || pathname.startsWith("/ask/")) return null;

  return (
    <header className="flex h-12 shrink-0 items-center gap-1 border-b border-line bg-surface px-2 md:hidden">
      <SidebarTrigger />
      <Link href="/ask" className="rounded-md px-1.5 py-1 font-mono text-sm tracking-tight text-ink">
        analyst
      </Link>
    </header>
  );
}
