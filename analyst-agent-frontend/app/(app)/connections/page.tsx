import { AlertTriangle } from "lucide-react";

import { ConnectionsView } from "@/components/connections/connections-view";
import { agentJson } from "@/lib/api/agent-client";
import { agentAwake } from "@/lib/api/agent-awake";
import type { Connection } from "@/lib/api/types";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Connections" };
export const dynamic = "force-dynamic";

export default async function ConnectionsPage() {
  const session = await requireSession("/connections");
  // The layout shows the agent waking; nothing here could load until it has.
  if (!(await agentAwake())) return null;

  let connections: Connection[] = [];
  let unreachable = false;
  try {
    connections = await agentJson<Connection[]>("/connections", { token: session.accessToken });
  } catch {
    unreachable = true;
  }
  const user = await getCurrentUser();

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8">
        <header className="mb-7">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Connections</h1>
          <p className="mt-1.5 max-w-[62ch] text-[0.875rem] leading-relaxed text-ink-muted">
            The databases and spreadsheets you can ask about. Questions are answered by reading
            them, never by writing to them.
          </p>
        </header>

        {unreachable ? (
          <p className="mb-5 flex items-start gap-2.5 rounded-md border border-fault/30 bg-fault-soft px-3.5 py-3 text-[0.875rem] text-fault">
            <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" strokeWidth={2} />
            <span>Could not reach the analyst service, so this list may be out of date.</span>
          </p>
        ) : null}

        <ConnectionsView connections={connections} isOwner={user?.role === "owner"} />
      </div>
    </main>
  );
}
