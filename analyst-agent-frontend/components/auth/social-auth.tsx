/**
 * Single sign-on, drawn but not wired.
 *
 * The agent authenticates with an email and a password and exposes no OAuth endpoint, so
 * there is nothing behind these yet. They ship disabled and say so rather than appearing
 * live and failing on click, which is the worse of the two ways to be honest about it.
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

function GitHubMark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" fill="currentColor" className="size-4 shrink-0">
      <path d="M12 .5A11.5 11.5 0 0 0 .5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.2-3.1-.13-.29-.53-1.46.1-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.5 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.75.81 1.2 1.84 1.2 3.1 0 4.43-2.7 5.4-5.27 5.69.42.36.78 1.06.78 2.14v3.17c0 .31.2.67.8.56A11.5 11.5 0 0 0 23.5 12 11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  );
}

const PROVIDERS = [
  {
    name: "Google",
    mark: <GoogleMark />,
    className: "border border-line bg-surface text-ink",
  },
  {
    name: "GitHub",
    mark: <GitHubMark />,
    className: "border border-transparent bg-[#18181b] text-white",
  },
] as const;

export function SocialAuth() {
  return (
    <div className="mt-6">
      <div className="flex items-center gap-3">
        <span aria-hidden className="h-px flex-1 bg-line" />
        <span className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-faint uppercase">
          Or continue with
        </span>
        <span aria-hidden className="h-px flex-1 bg-line" />
      </div>

      <div className="mt-4 flex flex-col gap-2.5">
        {PROVIDERS.map((provider) => (
          <button
            key={provider.name}
            type="button"
            disabled
            className={`flex h-10 cursor-not-allowed items-center justify-center gap-2.5 rounded-md text-[0.875rem] font-medium opacity-60 ${provider.className}`}
          >
            {provider.mark}
            Continue with {provider.name}
          </button>
        ))}
      </div>

      <p className="mt-3 text-center text-[0.75rem] text-ink-muted">
        Single sign-on is not enabled for this organisation yet.
      </p>
    </div>
  );
}
