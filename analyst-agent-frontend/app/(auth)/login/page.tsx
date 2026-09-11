import { login } from "@/actions/auth";
import { AuthCard } from "@/components/auth/auth-card";
import { AuthForm } from "@/components/auth/auth-form";
import { SocialAuth } from "@/components/auth/social-auth";

export const metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  // searchParams is a promise in Next 16.
  const { next } = await searchParams;

  return (
    <AuthCard
      title="Sign in"
      subtitle="Ask your database a question in plain English."
      footer={{ prompt: "No account yet?", href: "/register", label: "Create one" }}
    >
      <AuthForm
        action={login}
        next={typeof next === "string" ? next : undefined}
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

      <SocialAuth />
    </AuthCard>
  );
}
