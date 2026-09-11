import { RunHistory } from "@/components/ask/run-history";
import { agentJson } from "@/lib/api/agent-client";
import type { RunPage } from "@/lib/api/types";
import { requireSession } from "@/lib/auth/dal";

export const metadata = { title: "History" };
export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const session = await requireSession("/runs");

  let page: RunPage = { items: [], next_cursor: null };
  try {
    page = await agentJson<RunPage>("/runs?limit=50", { token: session.accessToken });
  } catch {
    // Render the empty state rather than an error page; the list is not load-bearing.
  }

  return (
    <main className="flex-1 overflow-y-auto bg-paper">
      <div className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8">
        <h1 className="text-[1.5rem] font-normal text-ink">History</h1>
        <p className="mt-2 max-w-[58ch] text-[0.9375rem] leading-relaxed text-ink-muted">
          Everything this organisation has asked. Results are not stored, so open a run to see
          the query and the answer, then ask it again for fresh numbers.
        </p>

        <section className="mt-9">
          <RunHistory initial={page} />
        </section>
      </div>
    </main>
  );
}
