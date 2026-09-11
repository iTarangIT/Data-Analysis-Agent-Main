import { cn } from "@/lib/utils";

/**
 * The card every screen is built from: a hairline, a white surface, and a shadow faint
 * enough to read as a lift rather than a drop.
 *
 * Not in `components/ui/`, which is shadcn registry output and gets overwritten by
 * `shadcn add`. This is ours.
 */
export function Panel({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("rounded-xl border border-line bg-surface shadow-card", className)}
      {...props}
    />
  );
}

/** The small-caps label above a group of panels. */
export function Eyebrow({ className, ...props }: React.ComponentProps<"h2">) {
  return (
    <h2
      className={cn(
        "text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-muted uppercase",
        className,
      )}
      {...props}
    />
  );
}
