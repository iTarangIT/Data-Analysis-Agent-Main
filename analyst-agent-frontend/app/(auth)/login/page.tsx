import Link from "next/link";

import { login } from "@/actions/auth";
import { AuthForm } from "@/components/auth/auth-form";

export const metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // searchParams is a promise in Next 16.
  const { next } = await searchParams;

  return (
    <>
      <h1 className="text-[1.625rem] leading-tight font-medium text-ink">Sign in</h1>
      <p className="mt-2 mb-8 text-[0.9375rem] text-ink-muted">
        Ask your database a question in plain English.
      </p>

      <AuthForm
        action={login}
        next={typeof next === "string" ? next : undefined}
        submitLabel="Sign in"
        pendingLabel="Signing in"
        fields={[
          { name: "email", label: "Email", type: "email", autoComplete: "email" },
          {
            name: "password",
            label: "Password",
            type: "password",
            autoComplete: "current-password",
          },
        ]}
      />

      <p className="mt-8 text-[0.875rem] text-ink-muted">
        No account yet?{" "}
        <Link href="/register" className="text-ink underline underline-offset-4">
          Create one
        </Link>
      </p>
    </>
  );
}
