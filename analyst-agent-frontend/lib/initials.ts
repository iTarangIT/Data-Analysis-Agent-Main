import type { User } from "@/lib/api/types";

/**
 * Two letters for an avatar. Falls back through name, then the local part of the email,
 * because `name` is nullable on every account the agent returns.
 */
export function initialsOf(user: Pick<User, "name" | "email"> | null): string {
  if (!user) return "?";
  const source = user.name?.trim() || user.email.split("@")[0] || user.email;
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const second = parts[1]?.[0] ?? "";
  return (first + second).toUpperCase();
}
