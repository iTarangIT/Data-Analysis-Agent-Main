import type { RunError } from "@/features/ask/run-types";

/**
 * What went wrong, and what to do about it.
 *
 * Each case names a next step, because "run failed" on its own leaves someone stuck. The
 * agent keeps its own messages deliberately vague for safety, so the recovery line is ours.
 */
function recovery(error: RunError): string | null {
  switch (error.code) {
    case "not_found":
      return "That connection is gone. Pick another, or add it again.";
    case "budget_exhausted":
      return "The daily token budget is spent. It refills over the next 24 hours.";
    case "rate_limited":
      return "Too many questions at once. Wait a moment and ask again.";
    case "unauthorized":
      return "Your session ended. Sign in again.";
    default:
      break;
  }

  if (error.kind === "truncated") {
    return "The run may still have finished. Check History before asking again.";
  }
  if (error.kind === "transport") {
    return "Check your connection and ask again.";
  }
  return null;
}

export function RunErrorPanel({ error }: { error: RunError }) {
  const next = recovery(error);

  return (
    <div role="alert" className="border-l-2 border-fault bg-paper-sunk px-4 py-3">
      <p className="text-[0.9375rem] text-ink">{error.message}</p>
      {next ? <p className="mt-1 text-[0.875rem] text-ink-muted">{next}</p> : null}
    </div>
  );
}
