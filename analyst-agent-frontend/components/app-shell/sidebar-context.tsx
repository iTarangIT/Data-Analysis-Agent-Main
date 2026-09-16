"use client";

import { Menu } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

import { SIDEBAR_COOKIE } from "./sidebar-cookie";

type SidebarState = {
  /** Desktop only: folded to the icon rail. */
  collapsed: boolean;
  toggleCollapsed: () => void;
  /** Mobile only: the drawer is open. */
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
};

const SidebarContext = createContext<SidebarState | null>(null);

export function SidebarProvider({
  defaultCollapsed = false,
  children,
}: {
  defaultCollapsed?: boolean;
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      document.cookie = `${SIDEBAR_COOKIE}=${next ? "1" : "0"}; path=/; max-age=31536000; samesite=lax`;
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ collapsed, toggleCollapsed, drawerOpen, setDrawerOpen }),
    [collapsed, toggleCollapsed, drawerOpen],
  );

  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}

export function useSidebar(): SidebarState {
  const context = useContext(SidebarContext);
  if (!context) throw new Error("useSidebar must be used inside SidebarProvider");
  return context;
}

/** Opens the drawer. Only rendered below `md`, where there is no sidebar to see. */
export function SidebarTrigger({ className }: { className?: string }) {
  const { setDrawerOpen } = useSidebar();
  return (
    <button
      type="button"
      onClick={() => setDrawerOpen(true)}
      aria-label="Open sidebar"
      className={cn(
        "flex size-9 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink md:hidden",
        className,
      )}
    >
      <Menu aria-hidden className="size-5" strokeWidth={1.75} />
    </button>
  );
}
