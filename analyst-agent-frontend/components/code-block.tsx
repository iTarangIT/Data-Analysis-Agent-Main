"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Code on the one dark surface in the product.
 *
 * Dark because SQL is the one thing here people read as code, and the contrast makes it a
 * distinct object rather than more prose. Never an editor: everything shown in one of these
 * is read, not written.
 */
export function CodeBlock({
  code,
  label,
  copyLabel = "code",
  className,
}: {
  code: string;
  /** A small caps heading inside the block, for when it needs naming. */
  label?: string;
  copyLabel?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused. The text is selectable, so this is not worth a toast.
    }
  }

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-lg bg-code-bg text-code-fg",
        className,
      )}
    >
      {label ? (
        <p className="px-4 pt-3 text-[0.625rem] font-semibold tracking-[0.08em] text-white/45 uppercase">
          {label}
        </p>
      ) : null}

      <pre
        className={cn(
          "overflow-x-auto px-4 pb-3.5 font-mono text-[0.8125rem] leading-[1.7] whitespace-pre-wrap",
          label ? "pt-2" : "pt-3.5",
        )}
      >
        <code>{code}</code>
      </pre>

      <button
        type="button"
        onClick={copy}
        aria-label={copied ? `${copyLabel} copied` : `Copy ${copyLabel}`}
        className="absolute top-2.5 right-2.5 rounded-md p-1.5 text-white/50 opacity-0 transition-opacity group-hover:opacity-100 hover:text-white focus-visible:opacity-100"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}
