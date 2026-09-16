"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import useSWR from "swr";

import { fetchThreads, THREADS_KEY } from "@/features/ask/threads";
import type { Thread } from "@/lib/api/types";
import { dayBucket } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * Every conversation this organisation has had, in the sidebar.
 *
 * Each entry is a link rather than a click handler, because the thread id lives in the URL:
 * that is what lets a conversation survive a navigation, a reload and a shared link.
 *
 * The sidebar sits in the app layout, which does not re-render when you navigate, so the list
 * the layout fetched is only the starting point. It is kept current through SWR: the ask
 * screen writes the new conversation in as soon as a question is sent, then revalidates once
 * the run settles. It still revalidates once on mount: `fallbackData` is never written to
 * SWR's cache, and the optimistic write needs a cached list to add to.
 *
 * Titles are the first question of the thread, truncated by the agent. There is no renaming,
 * because there is nowhere to store a name.
 */

function grouped(threads: Thread[]): { label: string; threads: Thread[] }[] {
  const groups: { label: string; threads: Thread[] }[] = [];
  for (const thread of threads) {
    const label = dayBucket(thread.last_run_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.threads.push(thread);
    else groups.push({ label, threads: [thread] });
  }
  return groups;
}

export function ThreadList({
  initial,
  onNavigate,
}: {
  initial: Thread[];
  onNavigate?: () => void;
}) {
  const { data: threads = initial } = useSWR(THREADS_KEY, fetchThreads, {
    fallbackData: initial,
  });
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeId = pathname === "/ask" ? searchParams.get("thread") : null;

  if (threads.length === 0) {
    return (
      <p className="px-2.5 py-2 text-[0.8125rem] leading-relaxed text-ink-muted">
        No chats yet. Ask a question and it will show up here.
      </p>
    );
  }

  return grouped(threads).map((group) => (
    <section key={group.label} className="mb-2">
      <h3 className="px-2.5 pt-3 pb-1.5 text-xs font-medium text-ink-faint">{group.label}</h3>

      <ul className="flex flex-col gap-px">
        {group.threads.map((thread) => {
          const active = thread.thread_id === activeId;
          const failed = thread.last_status === "error";
          const title = thread.title || "Untitled";
          return (
            <li key={thread.thread_id}>
              <Link
                href={`/ask?thread=${encodeURIComponent(thread.thread_id)}`}
                onClick={onNavigate}
                title={title}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
                  active ? "bg-surface-hover text-ink" : "text-ink hover:bg-surface-sunk",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{title}</span>
                {failed ? (
                  <>
                    <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-fault" />
                    <span className="sr-only">, last run failed</span>
                  </>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  ));
}
