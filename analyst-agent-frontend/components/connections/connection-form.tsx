"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";
import { toast } from "sonner";

import { createConnection } from "@/actions/connections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
function Submit() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} className="h-10 self-start px-5 text-[0.875rem]">
      {pending ? "Testing the connection" : "Add connection"}
    </Button>
  );
}

export function ConnectionForm() {
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
  }, [state, router]);

  return (
    <form ref={formRef} action={action} className="flex flex-col gap-5" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="name" className="text-[0.8125rem] text-ink">
          Name
        </Label>
        <Input
          id="name"
          name="name"
          placeholder="Warehouse"
          aria-invalid={state.fieldErrors?.name ? true : undefined}
          className="h-10 max-w-sm rounded-sm border-rule-paper bg-paper text-[0.9375rem]"
        />
        {state.fieldErrors?.name ? (
          <p className="text-[0.8125rem] text-fault">{state.fieldErrors.name}</p>
        ) : (
          <p className="text-[0.8125rem] text-ink-muted">What you will call it when asking.</p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="dsn" className="text-[0.8125rem] text-ink">
          Connection string
        </Label>
        <Input
          id="dsn"
          name="dsn"
          type="password"
          autoComplete="off"
          placeholder="postgresql://user:password@host:5432/database"
          aria-invalid={state.fieldErrors?.dsn ? true : undefined}
          className="h-10 rounded-sm border-rule-paper bg-paper font-mono text-[0.875rem]"
        />
        {state.fieldErrors?.dsn ? (
          <p className="text-[0.8125rem] text-fault">{state.fieldErrors.dsn}</p>
        ) : (
          <p className="max-w-[60ch] text-[0.8125rem] leading-relaxed text-ink-muted">
            Use a read-only role. The connection is tested before it is saved, and the password
            is encrypted at rest.
          </p>
        )}
      </div>

      <Submit />
    </form>
  );
}
