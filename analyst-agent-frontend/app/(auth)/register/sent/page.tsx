import { AuthCard } from "@/components/auth/auth-card";

export const metadata = { title: "Check your email" };

export default async function RegisterSentPage({ searchParams }: PageProps<"/register/sent">) {
  const { email } = await searchParams;

  return (
    <AuthCard
      title="Check your email"
      subtitle={
        typeof email === "string" ? (
          <>
            We sent a confirmation link to <span className="font-medium text-ink">{email}</span>.
          </>
        ) : (
          "We sent a confirmation link to the address you gave."
        )
      }
      footer={{ prompt: "Wrong address?", href: "/register", label: "Start again" }}
    >
      <p className="text-[0.875rem] text-ink">
        Open it on any device to finish creating your account. Your organisation is set up the
        moment you do.
      </p>
      <p className="mt-3 text-[0.8125rem] text-ink-muted">
        It can take a minute to arrive. If it does not, look in your spam folder.
      </p>
    </AuthCard>
  );
}
