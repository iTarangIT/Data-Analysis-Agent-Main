import Link from "next/link";

/**
 * The card both auth pages sit in. The wordmark stays the literal lowercase word in mono:
 * this product has no logo, and a monogram tile invented for a sign-in screen would be the
 * only mark in the entire interface.
 */
export function AuthCard({
  title,
  subtitle,
  footer,
  children,
}: {
  title: string;
  subtitle: string;
  footer: { prompt: string; href: string; label: string };
  children: React.ReactNode;
}) {
  return (
    <>
      <p className="mb-5 text-center font-mono text-sm tracking-tight text-ink-muted">
        analyst
      </p>

      <div className="rounded-xl border border-line bg-surface p-7 shadow-card">
        <h1 className="text-xl leading-tight font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1.5 mb-6 text-[0.875rem] text-ink-muted">{subtitle}</p>

        {children}

        <p className="mt-7 border-t border-line pt-5 text-center text-[0.8125rem] text-ink-muted">
          {footer.prompt}{" "}
          <Link href={footer.href} className="font-medium text-brand hover:underline">
            {footer.label}
          </Link>
        </p>
      </div>
    </>
  );
}
