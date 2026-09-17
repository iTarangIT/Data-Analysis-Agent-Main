"use client";

import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";

import { signInWithGoogle } from "@/actions/auth";

/**
 * Continue with Google.
 *
 * A form rather than a click handler, so it works before the page has hydrated: the server
 * action asks Supabase for Google's consent URL and redirects there. Supabase brings the person
 * back to /api/auth/callback, which finishes signing them in.
 */

function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-4 shrink-0">
      <path
        fill="#4285F4"
        d="M23.52 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.46a5.52 5.52 0 0 1-2.4 3.62v3.01h3.88c2.27-2.09 3.58-5.17 3.58-8.82Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.08 7.94-2.91l-3.88-3.01c-1.08.72-2.45 1.15-4.06 1.15-3.13 0-5.78-2.11-6.72-4.95H1.27v3.11A12 12 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.28a7.2 7.2 0 0 1 0-4.56V6.61H1.27a12 12 0 0 0 0 10.78l4.01-3.11Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.27 6.61l4.01 3.11C6.22 6.88 8.87 4.75 12 4.75Z"
      />
    </svg>
  );
}

function GoogleButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex h-10 w-full items-center justify-center gap-2.5 rounded-md border border-line bg-surface text-[0.875rem] font-medium text-ink transition-colors hover:bg-surface-sunk disabled:cursor-wait disabled:opacity-60"
    >
      {pending ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <GoogleMark />}
      Continue with Google
    </button>
  );
}

export function SocialAuth({ next }: { next?: string }) {
  return (
    <div className="mt-6">
      <div className="flex items-center gap-3">
        <span aria-hidden className="h-px flex-1 bg-line" />
        <span className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-faint uppercase">
          Or continue with
        </span>
        <span aria-hidden className="h-px flex-1 bg-line" />
      </div>

      <form action={signInWithGoogle} className="mt-4">
        {next ? <input type="hidden" name="next" value={next} /> : null}
        <GoogleButton />
      </form>
    </div>
  );
}
