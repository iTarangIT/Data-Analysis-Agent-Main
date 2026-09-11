import { AuthHero } from "@/components/auth/auth-hero";

/**
 * Split. The hero holds the ground; the form sits on paper, which is the same division the
 * rest of the app uses: the machine's side is dark, and what you work with is printed.
 *
 * Below the large breakpoint the hero is dropped rather than stacked. It is an argument, not
 * information, and on a phone it would only push the form off the screen.
 */
export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <AuthHero />
      <main className="flex items-center justify-center bg-paper px-5 py-12 sm:px-8">
        <div className="w-full max-w-[26rem]">{children}</div>
      </main>
    </div>
  );
}
