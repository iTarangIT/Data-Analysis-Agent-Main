"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

// Waking normally takes a minute or so; well past that, something other than sleep is wrong.
const SLOW_AFTER_MS = 180_000;

/**
 * Shown in place of a page while the agent wakes.
 *
 * It asks /api/health, which holds on until the agent answers, and reloads the route's data
 * once it does; the layout then renders the real page and this unmounts, which is what stops
 * the asking. A refresh that lands before the agent is fully up leaves this mounted, so it
 * keeps going rather than stopping at the first answer.
 */
export function WakingUp() {
  const router = useRouter();
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const slowTimer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);

    async function check() {
      const awake = await fetch("/api/health", { cache: "no-store" }).then(
        (response) => response.ok,
        () => false,
      );
      if (stopped) return;
      if (awake) router.refresh();
      // Longer after an answer, so the refresh has time to land before another is asked for.
      timer = setTimeout(check, awake ? 10_000 : 3_000);
    }

    void check();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(slowTimer);
    };
  }, [router]);

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-6 text-center">
      <Loader2 aria-hidden className="size-6 animate-spin text-brand" strokeWidth={2} />
      <h1 className="mt-5 text-xl font-semibold tracking-tight text-ink">
        Starting the analyst service
      </h1>
      <p className="mt-2 max-w-[44ch] text-[0.9375rem] leading-relaxed text-ink-muted">
        It sleeps when nobody has used it for a while, and waking takes about a minute. This page
        will load by itself.
      </p>
      {slow ? (
        <p role="status" className="mt-4 max-w-[44ch] text-[0.875rem] leading-relaxed text-fault">
          This is taking longer than usual. If it has not loaded in a few more minutes, the service
          may be down rather than asleep.
        </p>
      ) : null}
    </main>
  );
}
