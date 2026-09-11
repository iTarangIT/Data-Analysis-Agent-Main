"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { createConnection } from "@/actions/connections";
import { CodeBlock } from "@/components/code-block";
import { Eyebrow, Panel } from "@/components/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { FormState } from "@/actions/auth";

/**
 * Adding a connection.
 *
 * This form is also the connection test. The agent opens a real socket and runs SELECT 1
 * before it stores anything, so a failure here means the credentials genuinely do not work,
 * and the message belongs on the field rather than in a banner somewhere else on the page.
 *
 * Postgres only. A `web` connection is accepted at creation but fails at run time, which
 * would leave someone holding a connection that can never answer anything.
 */

// The product's whole claim is that it only ever reads. Handing over the grants that make
// that true at the database as well is the one piece of copy on this page worth its space.
const ROLE_SCRIPT = `CREATE ROLE analyst LOGIN PASSWORD 'a-strong-password';
GRANT CONNECT ON DATABASE your_db TO analyst;
GRANT USAGE ON SCHEMA public TO analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO analyst;`;

function Submit() {
  const { pending } = useFormStatus();
  return (
    <Button
      type="submit"
      disabled={pending}
      className="h-10 bg-brand px-5 text-[0.875rem] font-medium text-brand-fg hover:bg-brand-hover"
    >
      {pending ? (
        <>
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Testing the connection
        </>
      ) : (
        "Save connection"
      )}
    </Button>
  );
}

export function ConnectionForm({ onCancel }: { onCancel?: () => void }) {
  const router = useRouter();
  const [state, action] = useActionState<FormState, FormData>(createConnection, {});
  const formRef = useRef<HTMLFormElement>(null);
  const settled = useRef(state);

  useEffect(() => {
    if (state === settled.current) return;
    settled.current = state;

    const failed = state.message || (state.fieldErrors && Object.keys(state.fieldErrors).length);
    if (failed) {
      if (state.message) toast.error(state.message);
      return;
    }
    toast.success("Connection added");
    formRef.current?.reset();
    router.refresh();
    onCancel?.();
  }, [state, router, onCancel]);

  return (
    <Panel className="p-5">
      <Eyebrow>Postgres connection</Eyebrow>

      <form ref={formRef} action={action} className="mt-4 flex flex-col gap-4" noValidate>
        {state.message ? (
          <p
            role="alert"
            className="flex items-start gap-2.5 rounded-md border border-fault/30 bg-fault-soft px-3 py-2.5 text-[0.8125rem] text-fault"
          >
            <AlertTriangle aria-hidden className="mt-px size-4 shrink-0" strokeWidth={2} />
            <span>{state.message}</span>
          </p>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <Label
            htmlFor="name"
            className={cn(
              "text-[0.8125rem] font-medium",
              state.fieldErrors?.name ? "text-fault" : "text-ink",
            )}
          >
            Connection name
          </Label>
          <Input
            id="name"
            name="name"
            placeholder="Warehouse"
            aria-invalid={state.fieldErrors?.name ? true : undefined}
            className={cn(
              "h-10 rounded-md bg-surface text-sm placeholder:text-ink-faint",
              state.fieldErrors?.name ? "border-fault" : "border-line",
            )}
          />
          {state.fieldErrors?.name ? (
            <p className="text-[0.8125rem] text-fault">{state.fieldErrors.name}</p>
          ) : (
            <p className="text-[0.8125rem] text-ink-muted">What you will call it when asking.</p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label
            htmlFor="dsn"
            className={cn(
              "text-[0.8125rem] font-medium",
              state.fieldErrors?.dsn ? "text-fault" : "text-ink",
            )}
          >
            Connection string
          </Label>
          <Input
            id="dsn"
            name="dsn"
            type="password"
            autoComplete="off"
            placeholder="postgresql://user:password@host:5432/database"
            aria-invalid={state.fieldErrors?.dsn ? true : undefined}
            className={cn(
              "h-10 rounded-md bg-surface font-mono text-[0.8125rem] placeholder:text-ink-faint",
              state.fieldErrors?.dsn ? "border-fault" : "border-line",
            )}
          />
          {state.fieldErrors?.dsn ? (
            <p className="text-[0.8125rem] text-fault">{state.fieldErrors.dsn}</p>
          ) : (
            <p className="text-[0.8125rem] leading-relaxed text-ink-muted">
              Use a read-only role. The connection is tested before it is saved, and the
              password is encrypted at rest.
            </p>
          )}
        </div>

        <CodeBlock code={ROLE_SCRIPT} label="Read-only role" copyLabel="script" />

        <div className="flex items-center gap-2 pt-1">
          <Submit />
          {onCancel ? (
            <Button
              type="button"
              variant="ghost"
              onClick={onCancel}
              className="h-10 px-4 text-[0.875rem] text-ink-muted hover:text-ink"
            >
              Cancel
            </Button>
          ) : null}
        </div>
      </form>
    </Panel>
  );
}
