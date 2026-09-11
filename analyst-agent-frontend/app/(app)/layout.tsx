import { AppShell } from "@/components/app-shell/app-shell";
import { getCurrentUser, requireSession } from "@/lib/auth/dal";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // proxy.ts already made an optimistic check, but it reads a cookie and nothing more. This
  // is the gate that actually holds.
  await requireSession();
  const user = await getCurrentUser();

  return <AppShell user={user}>{children}</AppShell>;
}
