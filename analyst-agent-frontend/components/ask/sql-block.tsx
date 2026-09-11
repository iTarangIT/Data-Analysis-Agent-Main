"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

/**
 * The SQL the agent actually ran.
 *
 * Shown at nearly the size of the question above it, because the translation between the two
 * is the thing worth looking at, and because the person who set up the connection wants to
 * check the query is sane. Never a code editor: this is read, not edited.
 */
export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused. The SQL is selectable, so this is not worth a toast.
    }
  }

  return (
    <div className="group relative">
      <pre className="overflow-x-auto border-l-2 border-rule-paper py-0.5 pl-4 font-mono text-[0.9375rem] leading-[1.7] whitespace-pre-wrap text-ink">
        <code>{sql}</code>
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "SQL copied" : "Copy SQL"}
        className="absolute top-0 right-0 rounded-sm p-1.5 text-ink-muted opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}
