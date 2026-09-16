import { describe, expect, it } from "vitest";

import type { Thread } from "@/lib/api/types";

import { withAskedThread } from "./threads";

const older: Thread = {
  thread_id: "t-old", title: "How many devices?", run_count: 2,
  last_run_at: "2026-09-15T08:00:00Z", last_status: "done", connection_id: "c1",
};
const other: Thread = { ...older, thread_id: "t-other", title: "Which vehicle?" };

describe("withAskedThread", () => {
  const asked = { threadId: "t-new", question: "How many alerts?", connectionId: "c1", at: "2026-09-16T09:00:00Z" };

  it("puts a brand new conversation at the top, titled by its first question", () => {
    const next = withAskedThread([older, other], asked);
    expect(next.map((t) => t.thread_id)).toEqual(["t-new", "t-old", "t-other"]);
    expect(next[0]).toEqual({
      thread_id: "t-new", title: "How many alerts?", run_count: 1,
      last_run_at: "2026-09-16T09:00:00Z", last_status: "running", connection_id: "c1",
    });
  });

  it("moves a continued conversation to the top and keeps its original title", () => {
    const next = withAskedThread([other, older], { ...asked, threadId: "t-old" });
    expect(next.map((t) => t.thread_id)).toEqual(["t-old", "t-other"]);
    expect(next[0].title).toBe("How many devices?");
    expect(next[0].run_count).toBe(3);
    expect(next[0].last_status).toBe("running");
  });

  it("never mutates the list it was given", () => {
    const list = [older, other];
    withAskedThread(list, { ...asked, threadId: "t-old" });
    expect(list).toEqual([older, other]);
    expect(older.run_count).toBe(2);
  });
});
