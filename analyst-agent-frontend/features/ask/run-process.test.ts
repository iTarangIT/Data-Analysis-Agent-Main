import { describe, expect, it } from "vitest";
import { runReducer } from "./run-machine";
import { buildProcessSteps, confirmedRejections, processSummary } from "./run-process";
import { IDLE_RUN, type RunAction, type RunState, type Stage } from "./run-types";

const status = (stage: Stage): RunAction => ({ type: "status", data: { stage } });
const accept: RunAction = { type: "sql", data: { sql: "SELECT 1" } };
const done: RunAction = { type: "done", data: { run_id: "r1", duration_ms: 5100 } };
const drive = (...actions: RunAction[]) => actions.reduce(runReducer, IDLE_RUN);

describe("process record", () => {
  it("retains chronological retries and marks the rejected work", () => {
    const state = drive(status("router"), status("sql_gen"), status("sql_guard"), status("sql_gen"), status("sql_guard"), accept, status("db_exec"), status("answer"), done);
    const steps = buildProcessSteps(state);
    expect(steps.map((step) => step.stage)).toEqual(state.stageLog);
    expect(steps.map((step) => step.mark)).toEqual(["done", "hollow", "hollow", "done", "done", "done", "done"]);
    expect(steps.filter((step) => step.rejected)).toHaveLength(2);
    expect(steps[3].attempt).toBe(2);
    expect(processSummary(state.phase, state.durationMs!, state.attempts.length, confirmedRejections(state))).toBe("Answered in 5.1s · 2 queries, 1 rejected");
  });

  it("does not mark an earlier accepted query as rejected when another query follows", () => {
    const state = drive(status("sql_gen"), status("sql_guard"), accept, status("db_exec"), status("sql_gen"), status("sql_guard"), accept, status("db_exec"), done);
    expect(buildProcessSteps(state).every((step) => step.mark === "done")).toBe(true);
    expect(confirmedRejections(state)).toBe(0);
  });

  it.each(["error", "cancelled"] as const)("marks an interrupted %s check without claiming a rejection", (phase) => {
    const state: RunState = { ...drive(status("sql_gen"), status("sql_guard")), phase };
    expect(buildProcessSteps(state).at(-1)?.mark).toBe("hollow");
    expect(confirmedRejections(state)).toBe(0);
  });

  it("formats terminal states, clarification and saved runs without invented counts", () => {
    expect(processSummary("done", 5100, 1)).toBe("Answered in 5.1s · 1 query");
    expect(processSummary("done", 100, 0)).toBe("Answered in 0.1s · 0 queries");
    expect(processSummary("done", 5100)).toBe("Answered in 5.1s");
    expect(processSummary("error", 3200)).toBe("Failed after 3.2s");
    expect(processSummary("cancelled", 3200)).toBe("Stopped after 3.2s");
    expect(buildProcessSteps(IDLE_RUN)).toEqual([]);
  });
});
