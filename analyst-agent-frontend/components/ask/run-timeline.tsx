import { Check } from "lucide-react";

import { buildProcessSteps } from "@/features/ask/run-process";
import type { RunState } from "@/features/ask/run-types";
import { cn } from "@/lib/utils";

/** A static record of reached stages, including retries, inside the process disclosure. */
export function RunTimeline({ state }: { state: RunState }) {
  const steps = buildProcessSteps(state);
  if (!steps.length) return null;
  return (
    <ol aria-label="Run steps" className="flex flex-col">
      {steps.map((step, index) => (
        <li key={index} className="relative flex items-center gap-3 py-1">
          {index < steps.length - 1 ? (
            <span aria-hidden className="absolute top-[1.375rem] left-[0.4375rem] h-2 w-px bg-line" />
          ) : null}
          <span aria-hidden className={cn(
            "flex size-4 shrink-0 items-center justify-center rounded-full",
            step.mark === "done" ? "bg-brand" : "border border-line-strong bg-surface",
          )}>
            {step.mark === "done" ? <Check className="size-2.5 text-white" strokeWidth={3.5} /> : null}
          </span>
          <span className={cn("text-[0.8125rem]", step.mark === "done" ? "text-ink" : "text-ink-muted")}>
            {step.label}
            {step.attempt > 1 && (step.stage === "sql_gen" || step.stage === "sql_guard") ? ` · attempt ${step.attempt}` : ""}
            {step.rejected ? " · rejected" : step.mark === "hollow" ? " · not completed" : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
