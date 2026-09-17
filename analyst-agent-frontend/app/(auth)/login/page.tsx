import { login } from "@/actions/auth";
import { AuthCard } from "@/components/auth/auth-card";
import { AuthForm } from "@/components/auth/auth-form";
import { SocialAuth } from "@/components/auth/social-auth";

export const metadata = { title: "Sign in" };

// Set by the auth route handlers when a sign-in comes back failed.
const ERRORS: Record<string, string> = {
  google: "Google sign-in did not finish. Try again, or use your email and password.",
  confirm:
    "That confirmation link has expired or was already used. Sign in, or create the account again.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // searchParams is a promise in Next 16.
  const { next, error } = await searchParams;
  const returnTo = typeof next === "string" ? next : undefined;

  return (
    <AuthCard
      title="Sign in"
      subtitle="Ask your database a question in plain English."
      footer={{ prompt: "No account yet?", href: "/register", label: "Create one" }}
    >
      <AuthForm
        action={login}
        next={returnTo}
        message={typeof error === "string" ? ERRORS[error] : undefined}
        submitLabel="Sign in"
        pendingLabel="Authenticating"
        fields={[
          { name: "email", label: "Work email", type: "email", autoComplete: "email" },
          {
            name: "password",
            label: "Password",
            type: "password",
            autoComplete: "current-password",
          },
        ]}
      />

      <SocialAuth next={returnTo} />
    </AuthCard>
  );
}
