import type { RunState, Stage } from "./run-types";

/**
 * Which source answered, read back off the stages the run actually went through.
 *
 * Nobody picks a source any more: there are two, and the agent routes between them on whether
 * the question is about now or about what has been recorded. That makes "where did this number
 * come from" a question the reader can no longer answer by looking at what they selected, so
 * the transcript has to say it.
 *
 * Derived rather than reported, because the stage log already carries it. The agent emits
 * `web_tool` when it reads the dashboard and the SQL stages when it queries the database, so
 * there is nothing to add to the stream.
 */

export type Source = "dashboard" | "database";

const WEB: Stage = "web_tool";
const SQL: readonly Stage[] = ["sql_gen", "sql_guard", "db_exec"];

export function sourceOf(state: Pick<RunState, "stageLog">): Source | null {
  // Last match wins. A run that consulted both would be reporting the one it finished on,
  // which is the one the answer was written from.
  for (let i = state.stageLog.length - 1; i >= 0; i -= 1) {
    const stage = state.stageLog[i];
    if (stage === WEB) return "dashboard";
    if (SQL.includes(stage)) return "database";
  }
  return null;
}

/** What the label says. The dashboard's defining property is that it is live. */
export const SOURCE_LABEL: Record<Source, string> = {
  dashboard: "Read live from the dashboard",
  database: "Queried the IoT database",
};
