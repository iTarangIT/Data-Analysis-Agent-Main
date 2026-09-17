import { cookies } from "next/headers";

import { AppShell } from "@/components/app-shell/app-shell";
import { SIDEBAR_COOKIE } from "@/components/app-shell/sidebar-cookie";
import { agentJson } from "@/lib/api/agent-client";
import type { Thread } from "@/lib/api/types";
import { requireMember } from "@/lib/auth/dal";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // proxy.ts already redirected a signed-out navigation, but this is the gate that actually
  // holds. It also sends someone signed in with no organisation yet to name one.
  const { session, user } = await requireMember();

  // The thread list is only a starting point: layouts do not re-render on navigation, so the
  // sidebar keeps it current on the client. Not load-bearing either -- an unreachable agent
  // still renders the shell, with an empty list.
  const [threads, jar] = await Promise.all([
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
