import { describe, expect, it } from "vitest";

import type { SourceTable, TableDefinition } from "@/lib/api/types";

import { filterTables, holds, isDirty, missingJoins, toggle } from "./table-selection";

function definition(over: Partial<TableDefinition> = {}): TableDefinition {
  return {
    name: "batteries",
    comment: null,
    columns: [],
    primary_key: [],
    uniques: [],
    foreign_keys: [],
    checks: [],
    ...over,
  };
}

function table(over: Partial<SourceTable> = {}): SourceTable {
  return { name: "batteries", files: [], selected: true, definition: null, stats: null, ...over };
}

describe("toggle", () => {
  it("adds a table while there is room under the cap", () => {
    expect([...toggle(new Set(["alerts"]), "vehicles", 2)]).toEqual(["alerts", "vehicles"]);
  });

  // Dropping some other table to make room would change a choice nobody touched.
  it("refuses a table past the cap and leaves the choice as it was", () => {
    expect([...toggle(new Set(["alerts", "vehicles"]), "trips", 2)]).toEqual([
      "alerts",
      "vehicles",
    ]);
  });

  it("always lets a chosen table be cleared, even at the cap", () => {
    expect([...toggle(new Set(["alerts", "vehicles"]), "alerts", 2)]).toEqual(["vehicles"]);
  });

  it("returns a new set rather than changing the one it was given, so React re-renders", () => {
    const chosen = new Set(["alerts"]);
    toggle(chosen, "vehicles", 5);
    expect([...chosen]).toEqual(["alerts"]);
  });
});

describe("isDirty", () => {
  it("is clean when the same tables are chosen in a different order", () => {
    expect(isDirty(["alerts", "vehicles"], new Set(["vehicles", "alerts"]))).toBe(false);
  });

  // Comparing counts alone would call this clean and hide the Save button.
  it("is dirty when one table is swapped for another", () => {
    expect(isDirty(["alerts", "vehicles"], new Set(["alerts", "trips"]))).toBe(true);
  });

  it("is dirty when everything is cleared", () => {
    expect(isDirty(["alerts"], new Set())).toBe(true);
  });
});

describe("filterTables", () => {
  const names = ["alerts", "telemetry_gps", "Telemetry_CAN", "vehicles"];

  it("matches anywhere in the name, ignoring case", () => {
    expect(filterTables(names, "TELE")).toEqual(["telemetry_gps", "Telemetry_CAN"]);
  });

  it("shows every table for a blank query", () => {
    expect(filterTables(names, "   ")).toEqual(names);
  });
});

describe("missingJoins", () => {
  const batteries = table({
    name: "batteries",
    definition: definition({
      name: "batteries",
      foreign_keys: [
        { columns: ["dealer_id"], ref_table: "dealers", ref_columns: ["id"] },
        { columns: ["seller_id"], ref_table: "dealers", ref_columns: ["id"] },
      ],
    }),
  });
  const dealers = table({ name: "dealers", selected: false });

  it("names a key from a chosen table to one that is not chosen, once per pair", () => {
    expect(missingJoins([batteries, dealers], new Set(["batteries"]))).toEqual([
      { from: "batteries", to: "dealers" },
    ]);
  });

  it("says nothing once the referenced table is chosen too", () => {
    expect(missingJoins([batteries, dealers], new Set(["batteries", "dealers"]))).toEqual([]);
  });

  // The key belongs to a table the agent will not see, so there is no join to lose.
  it("ignores keys on a table that is not chosen", () => {
    expect(missingJoins([batteries, dealers], new Set(["dealers"]))).toEqual([]);
  });
});

describe("holds", () => {
  it("says a table is empty in so many words", () => {
    expect(holds({ rows: "empty" })).toBe("Empty");
  });

  it("gives a size as an estimate, never as a count", () => {
    expect(holds({ rows: "millions", rows_approx: 46_000_000 })).toBe("About 46,000,000 rows");
  });

  it("marks a partial estimate as a floor", () => {
    expect(holds({ rows: "millions", rows_approx: 46_000_000, rows_at_least: true })).toBe(
      "At least 46,000,000 rows",
    );
  });

  // A partition bound, not the newest row: the label claims no more than was measured.
  it("says where the newest partition with data ends", () => {
    expect(holds({ rows: "millions", rows_approx: 45_900_000, covered_to: "2026-07-01" })).toBe(
      "About 45,900,000 rows, newest partition with data ends 2026-07-01",
    );
  });

  it("draws nothing for a table whose contents were never measured", () => {
    expect(holds(null)).toBeNull();
  });
});
