"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { ConnectionForm } from "@/components/connections/connection-form";
import { ConnectionList } from "@/components/connections/connection-list";
import { Eyebrow } from "@/components/panel";
import { Button } from "@/components/ui/button";
import type { Connection } from "@/lib/api/types";

/**
 * The connections screen.
 *
 * The form is revealed rather than always on: once a database is connected the form is the
 * least interesting thing on the page, and leaving it open permanently made the list look
 * like a preamble to it. Still not a dialog -- it opens in place, below the grid, like the
 * delete confirmation does inside a card.
 */
export function ConnectionsView({ connections }: { connections: Connection[] }) {
  const [adding, setAdding] = useState(connections.length === 0);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <Eyebrow>Active connections</Eyebrow>
        {!adding ? (
          <Button
            onClick={() => setAdding(true)}
            className="h-9 bg-brand px-3.5 text-[0.8125rem] font-medium text-brand-fg hover:bg-brand-hover"
          >
            <Plus aria-hidden className="size-4" strokeWidth={2} />
            Add source
          </Button>
        ) : null}
      </div>

      <ConnectionList connections={connections}>
        {!adding ? (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="flex min-h-[11rem] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line-strong px-5 py-8 text-center transition-colors hover:border-brand hover:bg-brand-soft/40"
          >
            <span className="flex size-9 items-center justify-center rounded-full border border-line-strong text-ink-muted">
              <Plus aria-hidden className="size-4" strokeWidth={2} />
            </span>
            <span className="text-[0.875rem] font-medium text-ink">Connect a data source</span>
            <span className="max-w-[22ch] text-[0.75rem] text-ink-muted">
              A Postgres database the agent may read.
            </span>
          </button>
        ) : null}
      </ConnectionList>

      {adding ? (
        <ConnectionForm
          onCancel={connections.length === 0 ? undefined : () => setAdding(false)}
        />
      ) : null}
    </div>
  );
}
