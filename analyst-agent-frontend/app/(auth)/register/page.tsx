import { register } from "@/actions/auth";
import { AuthCard } from "@/components/auth/auth-card";
import { AuthForm } from "@/components/auth/auth-form";
import { SocialAuth } from "@/components/auth/social-auth";

export const metadata = { title: "Create an account" };

export default function RegisterPage() {
  return (
    <AuthCard
      title="Create an account"
      subtitle="You will be the owner of a new organisation. Teammates can join later."
      footer={{ prompt: "Already have an account?", href: "/login", label: "Sign in" }}
    >
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
          { name: "email", label: "Work email", type: "email", autoComplete: "email" },
          {
            name: "password",
            label: "Password",
            type: "password",
            autoComplete: "new-password",
            hint: "At least 12 characters.",
          },
        ]}
      />

      <SocialAuth />
    </AuthCard>
  );
}
