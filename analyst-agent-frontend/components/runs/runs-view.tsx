"use client";

import { useState } from "react";

import { Eyebrow, Panel } from "@/components/panel";
import { RunAudit } from "@/components/runs/run-audit";
import { RunRow } from "@/components/runs/run-row";
import { RunUsage } from "@/components/runs/run-usage";
import { Button } from "@/components/ui/button";
import type { RunPage, Usage } from "@/lib/api/types";

/**
 * The runs screen.
 *
 * One owner of the loaded page, because the list and the audit table are two readings of the
 * same rows. Usage no longer sits on those rows -- it comes from the agent's own aggregate --
 * so it keeps its own window and its own state.
 */
export function RunsView({ initial, usage }: { initial: RunPage; usage: Usage }) {
  const [items, setItems] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [loading, setLoading] = useState(false);

  async function more() {
    if (!cursor) return;
    setLoading(true);
    try {
      const response = await fetch(`/api/runs?limit=50&cursor=${encodeURIComponent(cursor)}`);
      if (response.ok) {
        const page = (await response.json()) as RunPage;
        setItems((current) => [...current, ...page.items]);
        setCursor(page.next_cursor);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-10">
      <RunUsage initial={usage} />

      <section className="flex flex-col gap-3">
        <Eyebrow>Runs</Eyebrow>

        {items.length === 0 ? (
          <Panel className="px-5 py-10 text-center text-[0.875rem] text-ink-muted">
            Nothing asked yet.
          </Panel>
        ) : (
          <>
            <Panel className="overflow-hidden">
              <ul>
                {items.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </ul>
            </Panel>

            {cursor ? (
              <Button
                variant="ghost"
                onClick={more}
                disabled={loading}
                className="h-9 self-start px-3 text-[0.875rem] text-ink-muted hover:text-ink"
              >
                {loading ? "Loading" : "Show older"}
              </Button>
            ) : null}
          </>
        )}
      </section>

      {items.length > 0 ? <RunAudit runs={items} /> : null}
    </div>
  );
}
