"use client";

import { RefreshCw, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";
import { toast } from "sonner";

import { refreshTables, saveTableSelection } from "@/actions/connections";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  filterTables,
  isDirty,
  missingJoins,
  toggle,
} from "@/features/connections/table-selection";
import type { ConnectionKind, ConnectionTables } from "@/lib/api/types";
import { when } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * Which of a connection's tables the agent may read.
 *
 * Nothing is sent until Save. Saving reads each chosen table's structure from the customer's
 * database, so a round trip per checkbox would be slow and would leave half a choice in force
 * if someone stopped part way. At the cap an unticked box is disabled rather than letting a new
 * choice push out an old one.
 */
export function TablePicker({
  connectionId,
  kind,
  catalog,
}: {
  connectionId: string;
  kind: ConnectionKind;
  catalog: ConnectionTables;
}) {
  const router = useRouter();
  const saved = useMemo(
    () => catalog.tables.filter((t) => t.selected).map((t) => t.name),
    [catalog],
  );
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(saved));
  const [query, setQuery] = useState("");
  const [saving, startSave] = useTransition();
  const [refreshing, startRefresh] = useTransition();

  const names = catalog.tables.map((t) => t.name);
  const fileOf = new Map(catalog.tables.map((t) => [t.name, t.files.join(", ")]));
  const shown = filterTables(names, query);
  const cap = catalog.max_selected;
  const atCap = chosen.size >= cap;
  const dirty = isDirty(saved, chosen);
  const lost = missingJoins(catalog.tables, chosen);
  const busy = saving || refreshing;

  function save() {
    startSave(async () => {
      const result = await saveTableSelection(connectionId, [...chosen]);
      if (result.message) {
        toast.error(result.message);
        return;
      }
      toast.success(`Saved. The agent now reads ${chosen.size} ${chosen.size === 1 ? "table" : "tables"}.`);
      router.refresh();
    });
  }

  function refresh() {
    startRefresh(async () => {
      const result = await refreshTables(connectionId);
      if (result.message) {
        toast.error(result.message);
        return;
      }
      const changes = [
        result.added?.length ? `New: ${result.added.join(", ")}.` : "",
        result.removed?.length ? `Gone: ${result.removed.join(", ")}.` : "",
      ].filter(Boolean);
      toast.success(changes.length ? `Refreshed. ${changes.join(" ")}` : "Refreshed. Nothing changed.");
      router.refresh();
    });
  }

  return (
    <Panel className="flex min-w-0 flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <Eyebrow>Tables</Eyebrow>
          <p className="mt-1 text-[0.8125rem] text-ink-muted">
            <span className="font-mono text-ink tabular-nums">{chosen.size}</span> of{" "}
            <span className="font-mono tabular-nums">{names.length}</span> chosen
          </p>
        </div>
        {kind === "postgres" ? (
          <Button
            variant="ghost"
            onClick={refresh}
            disabled={busy}
            className="h-8 px-2.5 text-[0.8125rem] text-ink-muted hover:bg-surface-sunk hover:text-ink"
          >
            <RefreshCw aria-hidden className="size-3.5" strokeWidth={2} />
            {refreshing ? "Refreshing" : "Refresh from database"}
          </Button>
        ) : null}
      </div>

      <div className="px-5 pt-4">
        <label className="relative block">
          <span className="sr-only">Find a table</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-ink-faint"
            strokeWidth={2}
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a table"
            className="h-9 bg-surface-sunk pl-8 text-[0.875rem]"
          />
        </label>
        <p className={cn("mt-2 text-[0.75rem]", atCap ? "text-warning" : "text-ink-muted")}>
          {atCap
            ? `That is the limit of ${cap}. Clear a table to choose another.`
            : `The agent can read up to ${cap}.`}
        </p>
      </div>

      <ul className="mt-2 max-h-[26rem] overflow-y-auto px-2 pb-2">
        {shown.map((name) => {
          const checked = chosen.has(name);
          const disabled = busy || (!checked && atCap);
          return (
            <li key={name}>
              <label
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 transition-colors",
                  disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-surface-sunk",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => setChosen((current) => toggle(current, name, cap))}
                  className="size-4 shrink-0 accent-brand"
                />
                <span
                  className={cn(
                    "min-w-0 truncate font-mono text-[0.8125rem]",
                    !checked && atCap ? "text-ink-faint" : "text-ink",
                  )}
                >
                  {name}
                </span>
                {fileOf.get(name) ? (
                  <span className="ml-auto max-w-[45%] shrink-0 truncate text-[0.75rem] text-ink-faint">
                    {fileOf.get(name)}
                  </span>
                ) : null}
              </label>
            </li>
          );
        })}
        {shown.length === 0 ? (
          <li className="px-3 py-6 text-center text-[0.8125rem] text-ink-muted">
            {names.length === 0
              ? `This ${kind === "file" ? "dataset" : "database"} has no tables the agent can read.`
              : `No table matches "${query.trim()}".`}
          </li>
        ) : null}
      </ul>

      {lost.length > 0 ? (
        <ul className="mx-5 mb-3 flex flex-col gap-1.5 rounded-md border border-warning/30 bg-warning/5 px-3 py-2.5">
          {lost.map(({ from, to }) => (
            <li key={`${from}-${to}`} className="text-[0.75rem] leading-relaxed text-ink">
              <span className="font-mono">{from}</span> has a key to{" "}
              <span className="font-mono">{to}</span>, which is not chosen, so the agent cannot
              join them.
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">
        {catalog.refreshed_at ? (
          <p className="mr-auto text-[0.75rem] text-ink-muted">
            Read from the {kind === "file" ? "files" : "database"} {when(catalog.refreshed_at)}
          </p>
        ) : null}
        <Button
          variant="ghost"
          onClick={() => setChosen(new Set(saved))}
          disabled={!dirty || busy}
          className="h-8 px-3 text-[0.8125rem]"
        >
          Discard changes
        </Button>
        <Button
          onClick={save}
          disabled={!dirty || busy}
          className="h-8 bg-brand px-3.5 text-[0.8125rem] font-medium text-brand-fg hover:bg-brand-hover"
        >
          {saving ? "Saving" : "Save choice"}
        </Button>
      </div>
    </Panel>
  );
}
