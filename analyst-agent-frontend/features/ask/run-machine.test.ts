import { describe, expect, it, vi } from "vitest";

import { runReducer } from "./run-machine";
import { IDLE_RUN, type RunAction, type RunState } from "./run-types";

const drive = (actions: RunAction[], from: RunState = IDLE_RUN): RunState =>
  actions.reduce(runReducer, from);

const submit: RunAction = {
  type: "@submit",
  question: "How many dealers do we have?",
  connectionId: "c1",
  threadId: "t1",
};

const stage = (s: string): RunAction =>
  ({ type: "status", data: { stage: s } }) as RunAction;

/** The sequence the agent's own integration test asserts for a clean SQL run. */
const HAPPY: RunAction[] = [
  submit,
  { type: "@open" },
  stage("router"),
  stage("sql_gen"),
  stage("sql_guard"),
  { type: "sql", data: { sql: "SELECT count(*) FROM dealers" } },
  stage("db_exec"),
  { type: "rows", data: { columns: ["count"], rows: [[3]], truncated: false } },
  stage("answer"),
  { type: "token", data: { text: "There are three dealers." } },
  { type: "done", data: { run_id: "r1", duration_ms: 1840 } },
];

describe("runReducer", () => {
  it.each<RunAction>([
    { type: "error", data: { message: "Rejected" } },
    { type: "@http", status: 500, message: "Unavailable" },
    { type: "@transport", message: "Disconnected" },
    { type: "@closed" }, { type: "@abort" },
  ])("freezes elapsed time for $type", (action) => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(1000);
      const running = drive([submit]);
      vi.advanceTimersByTime(3200);
      const settled = runReducer(running, action);
      expect(settled.durationMs).toBe(3200);
      vi.advanceTimersByTime(5000);
      expect(runReducer(settled, { type: "@closed" }).durationMs).toBe(3200);
    } finally { vi.useRealTimers(); }
  });
  describe("the happy path", () => {
    it("ends done with the sql, the rows and the answer", () => {
      const s = drive(HAPPY);

      expect(s.phase).toBe("done");
      expect(s.sql).toBe("SELECT count(*) FROM dealers");
      expect(s.result?.rows).toEqual([[3]]);
      expect(s.answer).toBe("There are three dealers.");
      expect(s.runId).toBe("r1");
      expect(s.durationMs).toBe(1840);
      expect(s.error).toBeNull();
    });

    it("records one attempt, accepted", () => {
      const s = drive(HAPPY);

      expect(s.attempts).toEqual([{ sql: "SELECT count(*) FROM dealers", rejected: false }]);
    });

    it("keeps the stages in the order they happened", () => {
      expect(drive(HAPPY).stageLog).toEqual([
        "router",
        "sql_gen",
        "sql_guard",
        "db_exec",
        "answer",
      ]);
    });
  });

  describe("a question the agent answers without SQL", () => {
    it("ends done with an answer and no sql", () => {
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        stage("answer"),
        { type: "token", data: { text: "Which region did you mean?" } },
        { type: "done", data: { run_id: "r2", duration_ms: 300 } },
      ]);

      expect(s.phase).toBe("done");
      expect(s.answer).toBe("Which region did you mean?");
      expect(s.sql).toBeNull();
      expect(s.result).toBeNull();
      expect(s.attempts).toEqual([]);
    });
  });

  describe("the guard rejecting a query", () => {
    it("accepts the stage going backwards and records both attempts", () => {
      // The agent retries after a rejection, so sql_gen follows sql_guard. A five-step
      // progress bar would render nonsense here.
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        stage("sql_gen"),
        stage("sql_guard"),
        stage("sql_gen"),
        stage("sql_guard"),
        { type: "sql", data: { sql: "SELECT 1" } },
        stage("db_exec"),
        { type: "rows", data: { columns: ["n"], rows: [[1]], truncated: false } },
        stage("answer"),
        { type: "token", data: { text: "One." } },
        { type: "done", data: { run_id: "r3", duration_ms: 900 } },
      ]);

      expect(s.phase).toBe("done");
      expect(s.attempts).toHaveLength(2);
      expect(s.attempts[0].rejected).toBe(true);
      expect(s.attempts[1]).toEqual({ sql: "SELECT 1", rejected: false });
      expect(s.stageLog.filter((x) => x === "sql_gen")).toHaveLength(2);
    });

    it("ends in error with no sql when the agent gives up", () => {
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        stage("sql_gen"),
        stage("sql_guard"),
        stage("sql_gen"),
        stage("sql_guard"),
        {
          type: "error",
          data: { message: "gave up after too many query attempts; try a narrower question" },
        },
      ]);

      expect(s.phase).toBe("error");
      expect(s.error?.kind).toBe("agent");
      expect(s.sql).toBeNull();
      expect(s.result).toBeNull();
      // The error event carries no run id, so a failed run cannot be deep-linked.
      expect(s.runId).toBeNull();
    });
  });

  describe("the answer buffer", () => {
    it("appends token events, so a chunked answer concatenates", () => {
      const s = drive([
        submit,
        stage("answer"),
        { type: "token", data: { text: "There are " } },
        { type: "token", data: { text: "three dealers." } },
      ]);

      expect(s.answer).toBe("There are three dealers.");
    });

    it("resets when the answer stage is entered again", () => {
      // Today one token event carries the whole answer, so re-entering must not double it.
      const s = drive([
        submit,
        stage("answer"),
        { type: "token", data: { text: "first draft" } },
        stage("answer"),
        { type: "token", data: { text: "final answer" } },
      ]);

      expect(s.answer).toBe("final answer");
    });
  });

  describe("failures before the stream opens", () => {
    it("reports an unknown connection as an http error", () => {
      const s = drive([
        submit,
        { type: "@http", status: 404, message: "connection not found", code: "not_found" },
      ]);

      expect(s.phase).toBe("error");
      expect(s.error).toMatchObject({ kind: "http", status: 404, code: "not_found" });
    });

    it("reports an exhausted budget", () => {
      const s = drive([
        submit,
        {
          type: "@http",
          status: 429,
          message: "daily token budget exhausted",
          code: "budget_exhausted",
        },
      ]);

      expect(s.error?.code).toBe("budget_exhausted");
    });
  });

  describe("the stream ending badly", () => {
    it("treats a close with no terminal event as a failure, not a success", () => {
      // What a serverless timeout looks like. Silently showing a half-run as complete would
      // be the worst outcome.
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        stage("sql_gen"),
        { type: "@closed" },
      ]);

      expect(s.phase).toBe("error");
      expect(s.error?.kind).toBe("truncated");
    });

    it("reports a dropped socket as a transport error", () => {
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        { type: "@transport", message: "network error" },
      ]);

      expect(s.error?.kind).toBe("transport");
    });

    it("ignores a close that arrives after done", () => {
      // The reader always reports how it finished, so this fires on every successful run.
      const s = drive([...HAPPY, { type: "@closed" }]);

      expect(s.phase).toBe("done");
      expect(s.error).toBeNull();
    });

    it("ignores events arriving after a terminal one", () => {
      const s = drive([
        ...HAPPY,
        { type: "token", data: { text: " and more" } },
        { type: "error", data: { message: "too late" } },
      ]);

      expect(s.phase).toBe("done");
      expect(s.answer).toBe("There are three dealers.");
    });
  });

  describe("cancelling", () => {
    it("lands in cancelled with no error, so nothing turns red", () => {
      const s = drive([submit, { type: "@open" }, stage("router"), { type: "@abort" }]);

      expect(s.phase).toBe("cancelled");
      expect(s.error).toBeNull();
    });

    it("keeps whatever had already arrived", () => {
      const s = drive([
        submit,
        { type: "@open" },
        stage("router"),
        stage("sql_gen"),
        stage("sql_guard"),
        { type: "sql", data: { sql: "SELECT 1" } },
        { type: "@abort" },
      ]);

      expect(s.sql).toBe("SELECT 1");
    });
  });

  describe("starting again", () => {
    it("clears the previous run", () => {
      const s = drive([...HAPPY, { ...submit, question: "and by region?" }]);

      expect(s.phase).toBe("connecting");
      expect(s.question).toBe("and by region?");
      expect(s.sql).toBeNull();
      expect(s.result).toBeNull();
      expect(s.answer).toBe("");
      expect(s.runId).toBeNull();
      expect(s.stageLog).toEqual([]);
    });

    it("keeps the thread, which is what makes a follow-up a follow-up", () => {
      const s = drive([...HAPPY, { ...submit, question: "and by region?" }]);

      expect(s.threadId).toBe("t1");
    });

    it("resets to idle", () => {
      expect(drive([...HAPPY, { type: "@reset" }])).toEqual(IDLE_RUN);
    });
  });

  describe("phases", () => {
    it("maps each stage to its phase", () => {
      const cases: Array<[string, string]> = [
        ["router", "routing"],
        ["sql_gen", "generating"],
        ["sql_guard", "guarding"],
        ["db_exec", "executing"],
        ["answer", "answering"],
      ];

      for (const [s, phase] of cases) {
        expect(drive([submit, stage(s)]).phase, s).toBe(phase);
      }
    });

    it("stays connecting until the first status arrives", () => {
      expect(drive([submit, { type: "@open" }]).phase).toBe("connecting");
    });
  });

  describe("a chart suggestion", () => {
    it("is kept alongside the table, never instead of it", () => {
      const s = drive([
        ...HAPPY.slice(0, -1),
        { type: "chart", data: { type: "bar", x: "month", y: ["units"] } },
        { type: "done", data: { run_id: "r1", duration_ms: 10 } },
      ]);

      expect(s.chart).toEqual({ type: "bar", x: "month", y: ["units"] });
      expect(s.result).not.toBeNull();
    });
  });

  describe("re-running in the same state", () => {
    it("drops a stale result when new sql arrives", () => {
      const s = drive([
        submit,
        stage("sql_guard"),
        { type: "sql", data: { sql: "SELECT 1" } },
        { type: "rows", data: { columns: ["n"], rows: [[1]], truncated: false } },
        stage("sql_gen"),
        stage("sql_guard"),
        { type: "sql", data: { sql: "SELECT 2" } },
      ]);

      // The old table belonged to the old query; showing it beside new SQL would be a lie.
      expect(s.sql).toBe("SELECT 2");
      expect(s.result).toBeNull();
    });
  });
});
