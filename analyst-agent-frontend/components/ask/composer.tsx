"use client";

import { ArrowUp } from "lucide-react";
import { useLayoutEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/** Past this the textarea scrolls inside itself instead of pushing the transcript away. */
const MAX_HEIGHT = 208;

/**
 * Where a question is written.
 *
 * Enter sends and Shift+Enter breaks the line, which is what every chat product has taught
 * people to expect. Enter is ignored while an input method is still composing a character, or
 * a Japanese or Chinese reader would send half a word each time they confirm a candidate.
 *
 * While a run is going the send button becomes Stop, and it has to stay enabled to do that:
 * it used to be disabled mid-run, which left no way to stop a run from the keyboard's side of
 * the screen.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  canSend,
  disabled = false,
  placeholder,
  notice,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  canSend: boolean;
  disabled?: boolean;
  placeholder: string;
  /** A line above the box for what has to happen before a question can be asked. */
  notice?: React.ReactNode;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, one line at a time, up to the cap.
  useLayoutEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function send() {
    if (busy || !canSend) return;
    onSubmit();
  }

  return (
    <div>
      {notice ? (
        <div className="mb-2 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 px-2 text-center text-[0.8125rem] text-ink-muted">
          {notice}
        </div>
      ) : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
        className={cn(
          "flex items-end gap-2 rounded-[1.75rem] border border-line bg-surface py-2 pr-2 pl-5 shadow-card transition-colors",
          "focus-within:border-brand/40 focus-within:ring-2 focus-within:ring-brand/15",
          disabled && "bg-surface-sunk",
        )}
      >
        <textarea
          ref={textarea}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            send();
          }}
          rows={1}
          disabled={disabled}
          aria-label="Your question"
          placeholder={placeholder}
          className="max-h-52 min-h-9 flex-1 resize-none self-center border-0 bg-transparent py-1.5 text-base leading-6 text-ink placeholder:text-ink-faint focus-visible:outline-none disabled:cursor-not-allowed"
        />

        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop"
            title="Stop"
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-brand-fg transition-colors hover:bg-brand-hover"
          >
            <span aria-hidden className="size-3 rounded-[3px] bg-current" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send"
            title="Send"
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand text-brand-fg transition-colors hover:bg-brand-hover disabled:opacity-40 disabled:hover:bg-brand"
          >
            <ArrowUp aria-hidden className="size-[1.125rem]" strokeWidth={2.25} />
          </button>
        )}
      </form>

      <p className="px-2 pt-2 text-center text-xs text-ink-faint">
        Read-only. Analyst never writes to your database.
      </p>
    </div>
  );
}
