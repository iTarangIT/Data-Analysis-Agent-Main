"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { deleteConnection } from "@/actions/connections";
import { Button } from "@/components/ui/button";
import type { Connection } from "@/lib/api/types";

/**
 * A hairline-ruled list, not a grid of cards.
 *
 * A connection is a row of facts: what it is called, what kind it is, whether its schema has
 * been read. Wrapping each one in a bordered, shadowed card would add three decorations per
 * item and say nothing extra.
 */
export function ConnectionList({ connections }: { connections: Connection[] }) {
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

  if (connections.length === 0) {
    return (
      <p className="border-t border-rule-paper py-8 text-[0.9375rem] text-ink-muted">
        No connections yet. Add one and you can start asking questions.
      </p>
    );
  }

  return (
    <ul className="border-t border-rule-paper">
      {connections.map((connection) => (
        <li
          key={connection.id}
          className="flex items-center gap-4 border-b border-rule-paper py-4"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-[0.9375rem] text-ink">{connection.name}</p>
            <p className="mt-0.5 font-mono text-[0.75rem] text-ink-muted">
              {connection.kind}
              {connection.has_schema_cache ? ", schema read" : ", schema not read yet"}
            </p>
          </div>

          {confirming === connection.id ? (
            <span className="flex items-center gap-2">
              <span className="text-[0.8125rem] text-ink-muted">Remove it?</span>
              <Button
                variant="ghost"
                onClick={() => setConfirming(null)}
                className="h-8 px-2 text-[0.8125rem]"
              >
                Keep
              </Button>
              <Button
                onClick={() => remove(connection)}
                disabled={pending}
                className="h-8 bg-fault px-3 text-[0.8125rem] text-paper hover:bg-fault/90"
              >
                {pending ? "Removing" : "Remove"}
              </Button>
            </span>
          ) : (
            <Button
              variant="ghost"
              onClick={() => setConfirming(connection.id)}
              aria-label={`Remove ${connection.name}`}
              className="h-8 px-2 text-ink-muted hover:text-ink"
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
