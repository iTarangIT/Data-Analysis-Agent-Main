import { describe, expect, it } from "vitest";
import { runReducer } from "./run-machine";
import { buildProcessSteps, confirmedRejections, plainSummary, processSummary } from "./run-process";
import { type Attempt, IDLE_RUN, type RunAction, type RunState, type Stage } from "./run-types";

const status = (stage: Stage): RunAction => ({ type: "status", data: { stage } });
const accept: RunAction = { type: "sql", data: { sql: "SELECT 1", what: "Counts dealers.", why: "You asked how many." } };
const refuse: RunAction = { type: "rejected", data: { sql: "DELETE FROM dealers", reason: "only SELECT is allowed", at: "guard" } };
const rows = (count: number, truncated = false): RunAction =>
  ({ type: "rows", data: { columns: ["n"], rows: Array.from({ length: count }, () => [1]), truncated, ms: 412 } });
const done: RunAction = { type: "done", data: { run_id: "r1", duration_ms: 5100 } };
const drive = (...actions: RunAction[]) => actions.reduce(runReducer, IDLE_RUN);
const steps = (state: RunState) => buildProcessSteps(state.stageLog, state.attempts, state.phase);

describe("process record", () => {
  it("retains chronological retries and marks the rejected work", () => {
    const state = drive(status("router"), status("sql_gen"), status("sql_guard"), status("sql_gen"), status("sql_guard"), accept, status("db_exec"), status("answer"), done);
    const record = steps(state);
    expect(record.map((step) => step.stage)).toEqual(state.stageLog);
    expect(record.map((step) => step.mark)).toEqual(["done", "hollow", "hollow", "done", "done", "done", "done"]);
    expect(record.filter((step) => step.rejected)).toHaveLength(2);
    expect(record[3].attempt).toBe(2);
    expect(processSummary(state.phase, state.durationMs!, state.attempts.length, confirmedRejections(state.attempts))).toBe("Answered in 5.1s · 2 queries, 1 rejected");
  });

  it("does not mark an earlier accepted query as rejected when another query follows", () => {
    const state = drive(status("sql_gen"), status("sql_guard"), accept, status("db_exec"), status("sql_gen"), status("sql_guard"), accept, status("db_exec"), done);
    expect(steps(state).every((step) => step.mark === "done")).toBe(true);
    expect(confirmedRejections(state.attempts)).toBe(0);
  });

  it.each(["error", "cancelled"] as const)("marks an interrupted %s check without claiming a rejection", (phase) => {
    const state: RunState = { ...drive(status("sql_gen"), status("sql_guard")), phase };
    expect(steps(state).at(-1)).toMatchObject({ mark: "hollow", note: "not completed" });
    expect(confirmedRejections(state.attempts)).toBe(0);
  });

  it("confirms a rejection from its reason, even when the model does not try again", () => {
    const state = drive(status("sql_gen"), status("sql_guard"), refuse, status("answer"), done);
    expect(confirmedRejections(state.attempts)).toBe(1);
    expect(steps(state)[1]).toMatchObject({ rejected: true, note: "rejected" });
  });

  it("says a query the database refused failed there, not at the guard", () => {
    const state = drive(status("sql_gen"), status("sql_guard"), { type: "rejected", data: { sql: "SELECT x", reason: "database error: no column x", at: "database" } });
    expect(steps(state)[1].note).toBe("failed in the database");
  });

  it("notes what the query found, how long it took, and what the answer was written from", () => {
    const state = drive(status("router"), status("sql_gen"), status("sql_guard"), accept, status("db_exec"), rows(2), status("answer"), done);
    expect(steps(state).map((step) => step.note)).toEqual([null, null, null, "2 rows · 412 ms", "from 2 rows"]);
  });

  it("numbers a retry and says when a result was cut off", () => {
    const state = drive(status("sql_gen"), status("sql_guard"), refuse, status("sql_gen"), status("sql_guard"), accept, status("db_exec"), rows(500, true), done);
    expect(steps(state).map((step) => step.note)).toEqual(["rejected", "rejected", "attempt 2", "attempt 2", "cut off at 500 rows · 412 ms"]);
  });

  it("formats terminal states, clarification and saved runs without invented counts", () => {
    expect(processSummary("done", 5100, 1)).toBe("Answered in 5.1s · 1 query");
    expect(processSummary("done", 100, 0)).toBe("Answered in 0.1s · 0 queries");
    expect(processSummary("done", 5100)).toBe("Answered in 5.1s");
    expect(processSummary("error", 3200)).toBe("Failed after 3.2s");
    expect(processSummary("cancelled", 3200)).toBe("Stopped after 3.2s");
    expect(buildProcessSteps([], [], "idle")).toEqual([]);
  });
});

describe("plain summary", () => {
  const answered = (patch: Partial<Attempt>): Attempt[] =>
    [{ sql: "SELECT 1", rejected: false, what: "Counts dealers.", why: "You asked how many.", rows: 1, truncated: false, ...patch }];

  it("gives the model's what and why, and a meaning worked out from the result", () => {
    expect(plainSummary(answered({}), "done")).toEqual({
      what: "Counts dealers.", why: "You asked how many.",
      means: "The answer uses everything this found; nothing was left out.",
    });
  });

  it("says when nothing matched", () => {
    expect(plainSummary(answered({ rows: 0 }), "done")?.means).toBe("Nothing in your data matched this.");
  });

  it("says when the answer only saw part of the result", () => {
    expect(plainSummary(answered({ rows: 500, truncated: true }), "done")?.means)
      .toBe("This found more than 500 results, so the answer only uses the first 500.");
  });

  it("leaves out a line the model did not write rather than printing it empty", () => {
    const summary = plainSummary(answered({ what: "", why: "" }), "done");
    expect(summary?.what).toBeUndefined();
    expect(summary?.why).toBeUndefined();
  });

  it("describes the result the answer came from, not a query refused before it", () => {
    const attempts = [{ sql: "DELETE FROM dealers", rejected: true, reason: "only SELECT", what: "Removes dealers." }, ...answered({})];
    expect(plainSummary(attempts, "done")?.what).toBe("Counts dealers.");
  });

  it("says nothing was looked up when no query ran", () => {
    expect(plainSummary([], "done")).toEqual({ what: "Nothing was looked up: this question didn't need your data." });
  });

  it("does not claim the answer came from the data when every query failed", () => {
    expect(plainSummary([{ sql: "DELETE FROM dealers", rejected: true, reason: "only SELECT" }], "done")?.means)
      .toBe("None of the queries worked, so the answer doesn't come from your data.");
  });

  it.each(["error", "cancelled"])("says nothing for a run that ended %s", (phase) => {
    expect(plainSummary(answered({}), phase)).toBeNull();
  });
});
