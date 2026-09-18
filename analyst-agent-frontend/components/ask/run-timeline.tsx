import { Check } from "lucide-react";

import type { ProcessStep } from "@/features/ask/run-process";
import { cn } from "@/lib/utils";

/** A static record of reached stages, including retries, inside the process disclosure. */
export function RunTimeline({ steps }: { steps: ProcessStep[] }) {
  if (!steps.length) return null;
  return (
    <ol aria-label="Run steps" className="flex flex-col">
      {steps.map((step, index) => (
        <li key={index} className="relative flex items-start gap-3 py-1">
          {index < steps.length - 1 ? (
            <span aria-hidden className="absolute top-[1.375rem] left-[0.4375rem] h-[calc(100%-1.25rem)] w-px bg-line" />
          ) : null}
          <span aria-hidden className={cn(
            "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full",
            step.mark === "done" ? "bg-brand" : "border border-line-strong bg-surface",
          )}>
            {step.mark === "done" ? <Check className="size-2.5 text-white" strokeWidth={3.5} /> : null}
          </span>
          <span className="min-w-0 text-[0.8125rem] leading-5">
            <span className={step.mark === "done" ? "text-ink" : "text-ink-muted"}>{step.label}</span>
            {step.note ? <span className="text-ink-muted"> · {step.note}</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
