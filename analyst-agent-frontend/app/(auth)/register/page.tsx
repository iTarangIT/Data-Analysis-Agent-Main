import Link from "next/link";

import { register } from "@/actions/auth";
import { AuthForm } from "@/components/auth/auth-form";

export const metadata = { title: "Create an account" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="text-[1.625rem] leading-tight font-medium text-ink">Create an account</h1>
      <p className="mt-2 mb-8 text-[0.9375rem] text-ink-muted">
        You will be the owner of a new organisation. Teammates can join later.
      </p>

      <AuthForm
        action={register}
        submitLabel="Create account"
        pendingLabel="Creating account"
        fields={[
          {
            name: "tenant_name",
            label: "Organisation",
            placeholder: "Acme Logistics",
            autoComplete: "organization",
          },
          { name: "email", label: "Email", type: "email", autoComplete: "email" },
          {
            name: "password",
            label: "Password",
            type: "password",
            autoComplete: "new-password",
            hint: "At least 12 characters.",
          },
        ]}
      />

      <p className="mt-8 text-[0.875rem] text-ink-muted">
        Already have an account?{" "}
        <Link href="/login" className="text-ink underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </>
  );
}
