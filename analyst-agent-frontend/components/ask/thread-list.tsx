"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import type { Thread } from "@/lib/api/types";
import { dayBucket, when } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * Every conversation this organisation has had.
 *
 * Each entry is a link rather than a click handler, because the thread id lives in the URL:
 * that is what lets a conversation survive a navigation, a reload and a shared link. The
 * page used to mint a fresh id on every render, which quietly ended the conversation every
 * time anyone looked at another screen.
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
  threads,
  activeId,
}: {
  threads: Thread[];
  activeId: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between gap-2 px-4">
        <p className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-muted uppercase">
          Threads
        </p>
        <Link
          href="/ask"
          aria-label="Start a new thread"
          title="Start a new thread"
          className="flex size-7 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink"
        >
          <Plus aria-hidden className="size-4" strokeWidth={2} />
        </Link>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {threads.length === 0 ? (
          <p className="px-2 py-3 text-[0.8125rem] leading-relaxed text-ink-muted">
            Nothing asked yet. Your conversations will collect here.
          </p>
        ) : (
          grouped(threads).map((group) => (
            <section key={group.label} className="mb-3">
              <h3 className="px-2 py-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] text-ink-faint uppercase">
                {group.label}
              </h3>

              <ul className="flex flex-col gap-0.5">
                {group.threads.map((thread) => {
                  const active = thread.thread_id === activeId;
                  return (
                    <li key={thread.thread_id}>
                      <Link
                        href={`/ask?thread=${encodeURIComponent(thread.thread_id)}`}
                        aria-current={active ? "true" : undefined}
                        className={cn(
                          "block rounded-md px-2.5 py-2 transition-colors",
                          active ? "bg-brand-soft" : "hover:bg-surface-sunk",
                        )}
                      >
                        <span
                          className={cn(
                            "block truncate text-[0.8125rem]",
                            active ? "font-medium text-brand" : "text-ink",
                          )}
                        >
                          {thread.title || "Untitled"}
                        </span>
                        <span className="mt-0.5 block truncate font-mono text-[0.6875rem] text-ink-muted">
                          {when(thread.last_run_at)}
                          {" · "}
                          {thread.run_count} run{thread.run_count === 1 ? "" : "s"}
                          {thread.last_status === "error" ? " · failed" : ""}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
