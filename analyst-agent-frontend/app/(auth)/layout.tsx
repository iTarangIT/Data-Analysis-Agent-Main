/**
 * One centred card on the ground, the same card the rest of the product is built from.
 *
 * This used to be a split, with a static English-to-SQL demonstration filling the left half.
 * The demonstration was an argument rather than information, and it only ever appeared above
 * the large breakpoint, which meant most of the people who needed convincing never saw it.
 */
export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-bg px-4 py-10">
      <main className="w-full max-w-[25rem]">{children}</main>
    </div>
  );
}
