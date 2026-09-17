import { redirect } from "next/navigation";

import { createOrganisation, logout } from "@/actions/auth";
import { AuthCard } from "@/components/auth/auth-card";
import { AuthForm } from "@/components/auth/auth-form";
import { getMembership, requireSession } from "@/lib/auth/dal";
import { safeNext } from "@/lib/auth/next";

export const metadata = { title: "Name your organisation" };

/**
 * The one question a first-time Google user has not answered: which organisation they are
 * creating. Email sign-ups name theirs on the sign-up form and never see this page.
 */
export default async function WelcomePage({ searchParams }: PageProps<"/welcome">) {
  const session = await requireSession("/welcome");
  const { next } = await searchParams;
  const destination = safeNext(next);

  const membership = await getMembership();
  if (membership.status === "member") redirect(destination);

  return (
    <AuthCard
      title="Name your organisation"
      subtitle={
        session.email ? (
          <>
            Signed in as <span className="font-medium text-ink">{session.email}</span>.
          </>
        ) : (
          "You are signed in."
        )
      }
      footer={{ prompt: "Not you?", action: logout, label: "Sign out" }}
    >
      <AuthForm
        action={createOrganisation}
        next={destination === "/ask" ? undefined : destination}
        submitLabel="Continue"
        pendingLabel="Creating organisation"
        fields={[
          {
            name: "tenant_name",
            label: "Organisation",
            placeholder: "Acme Logistics",
            autoComplete: "organization",
            hint: "You will be its owner. Teammates can join later.",
          },
        ]}
      />
    </AuthCard>
  );
}
