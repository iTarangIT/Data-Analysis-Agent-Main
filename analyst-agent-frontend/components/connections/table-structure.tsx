import { ChevronRight } from "lucide-react";

import { Eyebrow, Panel } from "@/components/panel";
import { holds } from "@/features/connections/table-selection";
import type {
  ConnectionTables,
  Relationship,
  TableDefinition,
  TableStats,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * What the agent is shown about the saved choice, and how it may join those tables.
 *
 * This mirrors the query tool's description: columns and keys, what each table holds as the
 * catalog measured it, and each join with whether a key declares it or only matching column
 * names suggest it. Nothing here is a row, because the agent is never given one.
 *
 * Each table opens in place with a native `<details>`, so there is no state to hold and no
 * dialog, and the keyboard and screen reader behaviour is the browser's own.
 */
export function TableStructure({ catalog }: { catalog: ConnectionTables }) {
  const chosen = catalog.tables.flatMap((t) =>
    t.selected && t.definition ? [{ definition: t.definition, stats: t.stats }] : [],
  );

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section className="flex flex-col gap-3">
        <Eyebrow>How they join</Eyebrow>
        <Panel className="px-5 py-4">
          {catalog.relationships.length === 0 ? (
            <p className="text-[0.8125rem] text-ink-muted">
              No key links the chosen tables, and no column names suggest a join.
            </p>
          ) : (
            <ul className="flex flex-col gap-2.5">
              {catalog.relationships.map((relationship) => (
                <Join
                  key={`${end(relationship.from_table, relationship.from_columns)}>${end(relationship.to_table, relationship.to_columns)}`}
                  relationship={relationship}
                />
              ))}
            </ul>
          )}
        </Panel>
      </section>

      <section className="flex flex-col gap-3">
        <Eyebrow>What the agent sees</Eyebrow>
        {chosen.length === 0 ? (
          <Panel className="px-5 py-6 text-[0.8125rem] text-ink-muted">
            Save a choice of tables to see their structure here.
          </Panel>
        ) : (
          <Panel className="divide-y divide-line overflow-hidden">
            {chosen.map(({ definition, stats }) => (
              <Structure key={definition.name} definition={definition} stats={stats} />
            ))}
          </Panel>
        )}
      </section>
    </div>
  );
}

function end(table: string, columns: string[]): string {
  return columns.length === 1 ? `${table}.${columns[0]}` : `${table}.(${columns.join(", ")})`;
}

const CARDINALITY: Record<Relationship["cardinality"], string> = {
  many_to_one: "many to one",
  one_to_one: "one to one",
};

/**
 * A guessed join has to look like a guess. The dashed underline is the visual cue and the words
 * say it again, so the difference never rests on the line alone.
 */
function Join({ relationship }: { relationship: Relationship }) {
  const inferred = relationship.origin === "inferred";
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <span
        className={cn(
          "font-mono text-[0.8125rem] text-ink",
          inferred && "underline decoration-line-strong decoration-dashed underline-offset-4",
        )}
      >
        {end(relationship.from_table, relationship.from_columns)}
        <span className="px-1.5 text-ink-faint">→</span>
        {end(relationship.to_table, relationship.to_columns)}
      </span>
      <span className="text-[0.75rem] text-ink-muted">
        {CARDINALITY[relationship.cardinality]}
        {inferred ? ", inferred from matching column names" : ""}
      </span>
    </li>
  );
}

function Structure({
  definition,
  stats,
}: {
  definition: TableDefinition;
  stats: TableStats | null;
}) {
  const holding = holds(stats);
  const singlePk = definition.primary_key.length === 1 ? definition.primary_key[0] : null;
  const unique = new Set(definition.uniques.filter((u) => u.length === 1).map((u) => u[0]));
  const references = new Map(
    definition.foreign_keys
      .filter((key) => key.columns.length === 1)
      .map((key) => [key.columns[0], end(key.ref_table, key.ref_columns)]),
  );
  const tableLevel = [
    ...(definition.primary_key.length > 1
      ? [`PRIMARY KEY (${definition.primary_key.join(", ")})`]
      : []),
    ...definition.uniques.filter((u) => u.length > 1).map((u) => `UNIQUE (${u.join(", ")})`),
    ...definition.foreign_keys
      .filter((key) => key.columns.length > 1)
      .map((key) => `(${key.columns.join(", ")}) → ${end(key.ref_table, key.ref_columns)}`),
    ...definition.checks.map((check) => `CHECK (${check})`),
  ];

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2.5 px-5 py-3 transition-colors hover:bg-surface-sunk [&::-webkit-details-marker]:hidden">
        <ChevronRight
          aria-hidden
          className="size-3.5 shrink-0 text-ink-faint group-open:rotate-90"
          strokeWidth={2}
        />
        <span className="min-w-0 truncate font-mono text-[0.875rem] font-medium text-ink">
          {definition.name}
        </span>
        <span className="ml-auto shrink-0 text-right text-[0.75rem] text-ink-muted">
          {holding ?? `${definition.columns.length} columns`}
        </span>
      </summary>

      <div className="px-5 pb-4">
        {definition.comment ? (
          <p className="mb-3 max-w-[62ch] text-[0.8125rem] text-ink-muted">{definition.comment}</p>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-line text-[0.6875rem] text-ink-muted">
                <th className="py-1.5 pr-4 font-medium">Column</th>
                <th className="py-1.5 pr-4 font-medium">Type</th>
                <th className="py-1.5 font-medium">Keys and rules</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {definition.columns.map((column) => {
                const notes = [
                  column.name === singlePk ? "primary key" : null,
                  unique.has(column.name) ? "unique" : null,
                  !column.nullable && column.name !== singlePk ? "not null" : null,
                ].filter((note) => note !== null);
                const reference = references.get(column.name);
                return (
                  <tr key={column.name} className="align-top">
                    <td className="py-1.5 pr-4 font-mono text-[0.8125rem] text-ink">
                      {column.name}
                      {column.comment ? (
                        <span className="block font-sans text-[0.75rem] text-ink-muted">
                          {column.comment}
                        </span>
                      ) : null}
                    </td>
                    <td className="py-1.5 pr-4 font-mono text-[0.8125rem] whitespace-nowrap text-ink-muted">
                      {column.type}
                    </td>
                    <td className="py-1.5 text-[0.75rem] text-ink-muted">
                      {notes.join(", ")}
                      {reference ? (
                        <span className="block font-mono text-[0.75rem] text-ink">
                          → {reference}
                        </span>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {tableLevel.length > 0 ? (
          <ul className="mt-3 flex flex-col gap-1">
            {tableLevel.map((rule) => (
              <li key={rule} className="font-mono text-[0.75rem] break-words text-ink-muted">
                {rule}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </details>
  );
}
