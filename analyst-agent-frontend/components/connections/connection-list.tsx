"use client";

import { Database, FileSpreadsheet, Trash2 } from "lucide-react";
import Link from "next/link";
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
 * The badge reads how many of the source's tables the agent may use, from `selected_tables`
 * and `total_tables`. None chosen out of some is the one state that stops a question from
 * being answered, so it is the one drawn as a warning. It is not a liveness probe and does not
 * claim to be one. The connection string is never shown because the agent never returns it.
 */

function badge(connection: Connection): { label: string; tone: string } {
  const { selected_tables: chosen, total_tables: total } = connection;
  if (total === 0) return { label: "Tables not read yet", tone: "bg-surface-sunk text-ink-muted" };
  if (chosen === 0) return { label: "No tables chosen", tone: "bg-warning/10 text-warning" };
  return { label: `${chosen} of ${total} tables`, tone: "bg-success/10 text-success" };
}

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
                badge(connection).tone,
              )}
            >
              {badge(connection).label}
            </span>
          </div>

          <p className="mt-4 truncate text-[0.9375rem] font-medium text-ink">
            {connection.name}
          </p>
          <p className="mt-0.5 font-mono text-[0.75rem] text-ink-muted">
            {connection.kind === "file"
              ? `${connection.file_count} ${connection.file_count === 1 ? "file" : "files"}`
              : connection.kind}
          </p>

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
              <>
                <Link
                  href={`/connections/${connection.id}/tables`}
                  className="text-[0.8125rem] font-medium text-brand transition-colors hover:text-brand-hover"
                >
                  {connection.kind === "file" ? "Tables and files" : "Choose tables"}
                </Link>
                <Button
                  variant="ghost"
                  onClick={() => setConfirming(connection.id)}
                  aria-label={`Remove ${connection.name}`}
                  className="ml-auto h-8 px-2 text-ink-muted hover:text-fault"
                >
                  <Trash2 className="size-4" strokeWidth={1.75} />
                </Button>
              </>
            )}
          </div>
        </Panel>
      ))}

      {children}
    </div>
  );
}
