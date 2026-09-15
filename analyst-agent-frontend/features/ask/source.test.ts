import { describe, expect, it } from "vitest";

import type { Stage } from "./run-types";

import { sourceOf } from "./source";

const at = (...stageLog: Stage[]) => ({ stageLog });

describe("sourceOf", () => {
  it("says nothing before any stage has happened", () => {
    expect(sourceOf(at())).toBeNull();
  });

  it("does not guess from the routing stage alone", () => {
    expect(sourceOf(at("router"))).toBeNull();
  });

  it("reads the dashboard from a web stage", () => {
    expect(sourceOf(at("router", "web_tool"))).toBe("dashboard");
  });

  it("reads the database from any of the SQL stages", () => {
    expect(sourceOf(at("router", "sql_gen"))).toBe("database");
    expect(sourceOf(at("router", "sql_gen", "sql_guard"))).toBe("database");
    expect(sourceOf(at("router", "sql_gen", "sql_guard", "db_exec"))).toBe("database");
  });

  // The guard sending the model back to rewrite its query is the common case, and it must not
  // change what the run says about where the answer came from.
  it("is unchanged by a rewritten query", () => {
    expect(sourceOf(at("router", "sql_gen", "sql_guard", "sql_gen", "sql_guard", "db_exec"))).toBe(
      "database",
    );
  });

  it("reports the source the answer was written from when a run used both", () => {
    expect(sourceOf(at("router", "sql_gen", "db_exec", "web_tool"))).toBe("dashboard");
    expect(sourceOf(at("router", "web_tool", "sql_gen", "db_exec"))).toBe("database");
  });

  it("ignores the answering stage, which belongs to neither", () => {
    expect(sourceOf(at("router", "web_tool", "answer"))).toBe("dashboard");
  });
});
