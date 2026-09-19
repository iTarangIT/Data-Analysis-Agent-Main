import { RunsView } from "@/components/runs/runs-view";
import { agentJson } from "@/lib/api/agent-client";
import { agentAwake } from "@/lib/api/agent-awake";
import type { RunPage, Usage } from "@/lib/api/types";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export const metadata = { title: "Runs" };
export const dynamic = "force-dynamic";

const NO_USAGE: Usage = {
  daily_token_budget: 0,
  tokens_last_24h: 0,
  runs_last_24h: 0,
  days: [],
};

export default async function RunsPage() {
  const session = await requireSession("/runs");
  // The layout shows the agent waking; nothing here could load until it has.
  if (!(await agentAwake())) return null;
  // Cached per request by the DAL, so asking again here costs nothing.
  const user = await getCurrentUser();

  // Independent reads, so they go together rather than one after the other. Neither is
  // load-bearing: a failure renders the empty state rather than an error page.
  const [page, usage] = await Promise.all([
    agentJson<RunPage>("/runs?limit=50", { token: session.accessToken }).catch(
      (): RunPage => ({ items: [], next_cursor: null }),
    ),
    agentJson<Usage>("/usage?days=30", { token: session.accessToken }).catch(() => NO_USAGE),
  ]);

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-5 py-8 sm:px-8">
        <header className="mb-7">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Runs</h1>
            {user ? (
              <span className="text-[0.875rem] text-ink-muted">{user.tenant_name}</span>
            ) : null}
          </div>
          <p className="mt-1.5 max-w-[62ch] text-[0.875rem] leading-relaxed text-ink-muted">
            Everything this organisation has asked, and what it spent. Results are not stored,
            so open a run to see the query and the answer, then ask it again for fresh numbers.
          </p>
        </header>

        <RunsView initial={page} usage={usage} />
      </div>
    </main>
  );
}
