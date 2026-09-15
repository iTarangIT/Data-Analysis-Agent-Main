"use client";

import { Database, FileSpreadsheet, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { deleteConnection } from "@/actions/connections";
import { Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import type { Connection, ConnectionKind } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * A grid of cards, one per database.
 *
 * The badge reads `has_schema_cache`, which is a real field: the agent cannot write SQL
 * against a database whose shape it has not read yet, so "schema learned" is the closest
 * thing this product has to a health check. It is not a liveness probe and does not claim
 * to be one. The connection string is never shown because the agent never returns it.
 */

const ICON: Record<ConnectionKind, React.ReactNode> = {
  postgres: <Database className="size-4" strokeWidth={1.75} />,
  file: <FileSpreadsheet className="size-4" strokeWidth={1.75} />,
};

export function ConnectionList({
  connections,
  children,
}: {
  connections: Connection[];
  /** The add tile, rendered as the last cell of the same grid. */
  children?: React.ReactNode;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [confirming, setConfirming] = useState<string | null>(null);

  function remove(connection: Connection) {
    startTransition(async () => {
      const result = await deleteConnection(connection.id);
      setConfirming(null);
      if (result.message) {
        toast.error(result.message);
        return;
      }
      toast.success(`Removed ${connection.name}`);
      router.refresh();
    });
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {connections.map((connection) => (
        <Panel key={connection.id} className="flex min-w-0 flex-col p-5">
          <div className="flex items-start justify-between gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand">
              {ICON[connection.kind] ?? ICON.postgres}
            </span>

            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold tracking-[0.06em] uppercase",
                connection.has_schema_cache
                  ? "bg-success/10 text-success"
                  : "bg-surface-sunk text-ink-muted",
              )}
            >
              {connection.has_schema_cache ? "Schema learned" : "No schema yet"}
            </span>
          </div>

          <p className="mt-4 truncate text-[0.9375rem] font-medium text-ink">
            {connection.name}
          </p>
          <p className="mt-0.5 font-mono text-[0.75rem] text-ink-muted">{connection.kind}</p>

          <div className="mt-5 flex items-center border-t border-line pt-3">
            {confirming === connection.id ? (
              <span className="flex w-full items-center gap-2">
                <span className="text-[0.8125rem] text-ink-muted">Remove it?</span>
                <Button
                  variant="ghost"
                  onClick={() => setConfirming(null)}
                  className="ml-auto h-8 px-2 text-[0.8125rem]"
                >
                  Keep
                </Button>
                <Button
                  onClick={() => remove(connection)}
                  disabled={pending}
                  className="h-8 bg-fault px-3 text-[0.8125rem] text-white hover:bg-fault/90"
                >
                  {pending ? "Removing" : "Remove"}
                </Button>
              </span>
            ) : (
              <Button
                variant="ghost"
                onClick={() => setConfirming(connection.id)}
                aria-label={`Remove ${connection.name}`}
                className="h-8 px-2 text-ink-muted hover:text-fault"
              >
                <Trash2 className="size-4" strokeWidth={1.75} />
              </Button>
            )}
          </div>
        </Panel>
      ))}

      {children}
    </div>
  );
}
