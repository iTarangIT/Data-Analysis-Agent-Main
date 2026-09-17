"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { FormState } from "@/actions/auth";

type Field = {
  name: string;
  label: string;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
};

type Props = {
  action: (state: FormState, formData: FormData) => Promise<FormState>;
  fields: Field[];
  submitLabel: string;
  pendingLabel: string;
  /** Where to return after signing in, carried through the form rather than the URL. */
  next?: string;
  /** A problem to show before anything is submitted, such as a sign-in that came back failed. */
  message?: string;
};

function Submit({ label, pendingLabel }: { label: string; pendingLabel: string }) {
  // useFormStatus reads the enclosing form, so the button knows without being told.
  const { pending } = useFormStatus();
  return (
    <Button
      type="submit"
      disabled={pending}
      className="mt-1 h-10 w-full bg-brand text-sm font-medium text-brand-fg hover:bg-brand-hover"
    >
      {pending ? (
        <>
          <Loader2 aria-hidden className="size-4 animate-spin" />
          {pendingLabel}
        </>
      ) : (
        label
      )}
    </Button>
  );
}

export function AuthForm({ action, fields, submitLabel, pendingLabel, next, message }: Props) {
  const [state, formAction] = useActionState<FormState, FormData>(action, { message });

  return (
    <form action={formAction} className="flex flex-col gap-4" noValidate>
      {next ? <input type="hidden" name="next" value={next} /> : null}

      {/* Form-level rather than under the email field, which is where a mockup would put it.
          The login action collapses every failure into one message on purpose, so that a
          wrong password and an email with no account are indistinguishable; pinning that
          message to a field would undo the protection by implying which half was wrong. */}
      {state.message ? (
        <p
          role="alert"
          className="rounded-md border border-fault/30 bg-fault-soft px-3 py-2 text-[0.8125rem] text-fault"
        >
          {state.message}
        </p>
      ) : null}

      {fields.map((field) => {
        const error = state.fieldErrors?.[field.name];
        const describedBy = error
          ? `${field.name}-error`
          : field.hint
            ? `${field.name}-hint`
            : undefined;

        return (
          <div key={field.name} className="flex flex-col gap-1.5">
            <Label
              htmlFor={field.name}
              className={cn(
                "text-[0.8125rem] font-medium",
                error ? "text-fault" : "text-brand",
              )}
            >
              {field.label}
            </Label>
            <Input
              id={field.name}
              name={field.name}
              // React resets an uncontrolled form after its action completes, so a rejected
              // submit would otherwise wipe everything. Passwords are deliberately not kept.
              defaultValue={field.type === "password" ? undefined : state.values?.[field.name]}
              key={`${field.name}-${state.values?.[field.name] ?? ""}`}
              type={field.type ?? "text"}
              autoComplete={field.autoComplete}
              placeholder={field.placeholder}
              required={field.required !== false}
              aria-invalid={error ? true : undefined}
              aria-describedby={describedBy}
              className={cn(
                "h-10 rounded-md bg-surface text-sm text-ink placeholder:text-ink-faint",
                error ? "border-fault" : "border-line",
              )}
            />
            {error ? (
              <p id={`${field.name}-error`} className="text-[0.8125rem] text-fault">
                {error}
              </p>
            ) : field.hint ? (
              <p id={`${field.name}-hint`} className="text-[0.8125rem] text-ink-muted">
                {field.hint}
              </p>
            ) : null}
          </div>
        );
      })}

      <Submit label={submitLabel} pendingLabel={pendingLabel} />
    </form>
  );
}
