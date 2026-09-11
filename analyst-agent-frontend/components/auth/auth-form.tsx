"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
};

function Submit({ label, pendingLabel }: { label: string; pendingLabel: string }) {
  // useFormStatus reads the enclosing form, so the button knows without being told.
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} className="mt-2 h-11 w-full text-[0.9375rem]">
      {pending ? pendingLabel : label}
    </Button>
  );
}

export function AuthForm({ action, fields, submitLabel, pendingLabel, next }: Props) {
  const [state, formAction] = useActionState<FormState, FormData>(action, {});

  return (
    <form action={formAction} className="flex flex-col gap-5" noValidate>
      {next ? <input type="hidden" name="next" value={next} /> : null}

      {state.message ? (
        <p
          role="alert"
          className="border-l-2 border-fault bg-paper-sunk px-3 py-2 text-sm text-ink"
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
          <div key={field.name} className="flex flex-col gap-2">
            <Label htmlFor={field.name} className="text-[0.8125rem] font-medium text-ink">
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
              className="h-11 rounded-sm border-rule-paper bg-paper text-[0.9375rem] text-ink"
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
