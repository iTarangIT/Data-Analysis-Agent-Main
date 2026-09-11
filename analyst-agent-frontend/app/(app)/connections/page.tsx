import { ConnectionForm } from "@/components/connections/connection-form";
import { ConnectionList } from "@/components/connections/connection-list";
import { agentJson } from "@/lib/api/agent-client";
import type { Connection } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Connections" };
export const dynamic = "force-dynamic";

export default async function ConnectionsPage() {
  const session = await requireSession("/connections");

  let connections: Connection[] = [];
  let unreachable = false;
  try {
    connections = await agentJson<Connection[]>("/connections", { token: session.accessToken });
  } catch {
    unreachable = true;
  }

  return (
    <main className="flex-1 overflow-y-auto bg-paper">
      <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8">
        <h1 className="text-[1.5rem] font-normal text-ink">Connections</h1>
        <p className="mt-2 max-w-[58ch] text-[0.9375rem] leading-relaxed text-ink-muted">
          The databases you can ask about. Questions are answered by reading them, never by
          writing to them.
        </p>

        {unreachable ? (
          <p className="mt-6 border-l-2 border-fault bg-paper-sunk px-4 py-3 text-[0.9375rem] text-ink">
            Could not reach the analyst service, so this list may be out of date.
          </p>
        ) : null}

        <section className="mt-9">
          <ConnectionList connections={connections} />
        </section>

        <section className="mt-10">
          <h2 className="mb-5 text-[1.0625rem] font-medium text-ink">Add a connection</h2>
          <ConnectionForm />
        </section>
      </div>
    </main>
  );
}
