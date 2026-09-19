"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

// Waking normally takes a minute or so; well past that, something other than sleep is wrong.
const SLOW_AFTER_MS = 180_000;

/**
 * Shown in place of a page while the agent wakes.
 *
 * The browser does the waking. Render starts a sleeping free service only for a request from
 * outside Render, and this app's server is on Render: its checks were turned away in under a
 * second, for minutes on end, while one request from outside woke the agent at once. So this
 * sends the agent's /health a request of its own, opaque and unread, and keeps one in flight
 * until the agent is up.
 *
 * Whether it is up comes from /api/health, which the host holds while the agent wakes. Once it
 * answers, the route's data is reloaded; the layout then renders the real page and this
 * unmounts, which is what stops the asking. A refresh that lands before the agent is fully up
 * leaves this mounted, so it keeps going rather than stopping at the first answer.
 */
export function WakingUp({ wakeUrl }: { wakeUrl: string }) {
  const router = useRouter();
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    let stopped = false;
    let waking = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const slowTimer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);

    function wake() {
      if (waking) return;
      waking = true;
      void fetch(wakeUrl, { mode: "no-cors", cache: "no-store" })
        .catch(() => undefined)
        .finally(() => {
          waking = false;
        });
    }

    async function check() {
      const awake = await fetch("/api/health", { cache: "no-store" }).then(
        (response) => response.ok,
        () => false,
      );
      if (stopped) return;
      if (awake) router.refresh();
      else wake();
      // Longer after an answer, so the refresh has time to land before another is asked for.
      timer = setTimeout(check, awake ? 10_000 : 3_000);
    }

    wake();
    void check();
    return () => {
      stopped = true;
      clearTimeout(timer);
      clearTimeout(slowTimer);
    };
  }, [router, wakeUrl]);

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
