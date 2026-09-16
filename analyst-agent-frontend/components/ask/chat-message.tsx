"use client";

import { Check, Copy, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Message, MessageContent } from "@/components/ui/message";
import { Response } from "@/components/ui/response";
import { cn } from "@/lib/utils";

/**
 * The pieces of a conversation: your question, the agent's reply, and what you can do with it.
 *
 * Laid out like every chat product people already know. Your question is a grey bubble on the
 * right; the reply has no bubble and no avatar and uses the column's full width, because it is
 * where the tables and charts go and they need the room.
 */

export function UserMessage({ children }: { children: React.ReactNode }) {
  return (
    <Message from="user" className="py-0">
      <MessageContent
        variant="flat"
        className="rounded-3xl px-4 py-2.5 text-base leading-relaxed break-words whitespace-pre-wrap group-[.is-user]:max-w-[85%] sm:group-[.is-user]:max-w-[75%]"
      >
        {children}
      </MessageContent>
    </Message>
  );
}

export function AssistantMessage({ children }: { children: React.ReactNode }) {
  return (
    // `min-w-0` down the chain, or a result table five hundred columns wide stretches the
    // transcript instead of scrolling inside its own box.
    <Message from="assistant" className="py-0">
      <MessageContent
        variant="flat"
        className="min-w-0 flex-1 gap-4 overflow-visible rounded-none text-base"
      >
        {children}
      </MessageContent>
    </Message>
  );
}

/**
 * The answer, as markdown.
 *
 * `shown` is the typed-out part and `full` the whole of it. While the two differ the visible
 * copy is hidden from assistive tech, which reads the complete answer instead of a sentence
 * that grows under it. Once typing finishes they are the same and the visible copy is all
 * there is.
 */
export function AnswerText({ shown, full }: { shown: string; full: string }) {
  const typing = shown !== full;
  return (
    <>
      <div aria-hidden={typing || undefined} className="min-w-0">
        <Response className="text-base leading-7 text-ink [&_li]:my-1 [&_ol]:my-3 [&_p]:my-3 [&_ul]:my-3">
          {shown}
        </Response>
      </div>
      {typing ? <p className="sr-only">{full}</p> : null}
    </>
  );
}

/**
 * Copy, ask again, and the run's details.
 *
 * Always shown under the newest reply. Under older ones it waits for a hover or focus on
 * desktop, as in any chat app, so a long thread is not a column of repeated buttons; it stays
 * put while the details are open. Touch screens have no hover, so there it is always shown.
 *
 * Asking again is how you get numbers back: results are never stored, only how they were
 * reached.
 */
export function MessageActions({
  copyText,
  onAskAgain,
  persistent,
  children,
}: {
  copyText?: string | null;
  /** Absent when a question cannot be sent right now. */
  onAskAgain?: () => void;
  persistent: boolean;
  /** The run details toggle, which lays its panel out across the row. */
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "-mt-1 -ml-2 flex flex-wrap items-center gap-0.5",
        !persistent &&
          "transition-opacity md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100 md:has-[[aria-expanded=true]]:opacity-100",
      )}
    >
      {copyText ? <CopyButton text={copyText} /> : null}
      <ActionButton
        label="Ask again"
        title="Results are not stored. Ask again for fresh numbers."
        onClick={onAskAgain}
        disabled={!onAskAgain}
      >
        <RotateCcw className="size-4" strokeWidth={1.75} />
      </ActionButton>
      {children}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused. The answer is selectable, so this is not worth a toast.
    }
  }

  return (
    <ActionButton label={copied ? "Copied" : "Copy answer"} onClick={copy}>
      {copied ? (
        <Check className="size-4 text-success" strokeWidth={2} />
      ) : (
        <Copy className="size-4" strokeWidth={1.75} />
      )}
    </ActionButton>
  );
}

function ActionButton({
  label,
  title,
  onClick,
  disabled,
  children,
}: {
  label: string;
  title?: string;
  onClick?: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={title ?? label}
      className="flex size-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-sunk hover:text-ink disabled:pointer-events-none disabled:opacity-40"
    >
      <span aria-hidden className="flex">
        {children}
      </span>
    </button>
  );
}
