import { cookies } from "next/headers";

import { AppShell } from "@/components/app-shell/app-shell";
import { SIDEBAR_COOKIE } from "@/components/app-shell/sidebar-cookie";
import { agentJson } from "@/lib/api/agent-client";
import type { Thread } from "@/lib/api/types";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // proxy.ts already made an optimistic check, but it reads a cookie and nothing more. This
  // is the gate that actually holds.
  const session = await requireSession();

  // The thread list is only a starting point: layouts do not re-render on navigation, so the
  // sidebar keeps it current on the client. Not load-bearing either -- an unreachable agent
  // still renders the shell, with an empty list.
  const [user, threads, jar] = await Promise.all([
    getCurrentUser(),
    agentJson<Thread[]>("/runs/threads?limit=30", { token: session.accessToken }).catch(
      (): Thread[] => [],
    ),
    cookies(),
  ]);

  return (
    <AppShell
      user={user}
      threads={threads}
      collapsed={jar.get(SIDEBAR_COOKIE)?.value === "1"}
    >
      {children}
    </AppShell>
  );
}
