import { cookies } from "next/headers";

import { AppShell } from "@/components/app-shell/app-shell";
import { SIDEBAR_COOKIE } from "@/components/app-shell/sidebar-cookie";
import { WakingUp } from "@/components/app-shell/waking-up";
import { agentJson } from "@/lib/api/agent-client";
import { agentAwake } from "@/lib/api/agent-awake";
import type { Thread } from "@/lib/api/types";
import { requireMember, requireSession } from "@/lib/auth/dal";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // proxy.ts already redirected a signed-out navigation, but this is the gate that actually
  // holds.
  const session = await requireSession();
  const [awake, jar] = await Promise.all([agentAwake(), cookies()]);
  const collapsed = jar.get(SIDEBAR_COOKIE)?.value === "1";
  // Without the agent there is no account to read, but the sign-in still says who this is.
  const signedIn = session.email ? { name: null, email: session.email, tenant_name: null } : null;

  // Asleep, the agent would make every read below wait out its timeout and then render as if
  // this person had no organisation and no connections. Say it is waking instead; the panel
  // reloads the page once it answers.
  if (!awake) {
    return (
      <AppShell user={signedIn} collapsed={collapsed}>
        <WakingUp />
      </AppShell>
    );
  }

  // Also sends someone signed in with no organisation yet to name one.
  const { user } = await requireMember();

  // The thread list is only a starting point: layouts do not re-render on navigation, so the
  // sidebar keeps it current on the client. Not load-bearing either -- an unreachable agent
  // still renders the shell, with an empty list.
  const threads = await agentJson<Thread[]>("/runs/threads?limit=30", {
    token: session.accessToken,
  }).catch((): Thread[] => []);

  return (
    <AppShell user={user ?? signedIn} threads={threads} collapsed={collapsed}>
      {children}
    </AppShell>
  );
}
