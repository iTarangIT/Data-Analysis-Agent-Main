"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { agentJson } from "@/lib/api/agent-client";
import { ApiError } from "@/lib/api/errors";
import type { Connection, ConnectionTables, TablesRefresh } from "@/lib/api/types";
import { getSession } from "@/lib/auth/dal";

import type { FormState } from "./auth";

/**
 * Connections.
 *
 * Every export re-checks the session. A server action is reachable by a direct POST, not only
 * through the form that renders it, so trusting `proxy.ts` here would be trusting a check
 * that a matcher change could silently remove.
 */

const CreateSchema = z.object({
  name: z.string().min(1, { error: "Name this connection." }).max(200),
  dsn: z
    .string()
    .min(1, { error: "Paste the connection string." })
    .max(2000)
    .refine((v) => v.startsWith("postgresql://") || v.startsWith("postgresql+psycopg://"), {
      error: "Start with postgresql:// or postgresql+psycopg://",
    }),
});

export async function createConnection(
  _prev: FormState,
  formData: FormData,
): Promise<FormState> {
  const session = await getSession();
  if (!session) return { message: "Your session has ended. Sign in again." };

  const parsed = CreateSchema.safeParse({
    name: formData.get("name"),
    dsn: formData.get("dsn"),
  });
  if (!parsed.success) {
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const key = String(issue.path[0] ?? "form");
      if (!fieldErrors[key]) fieldErrors[key] = issue.message;
    }
    return { fieldErrors };
  }

  try {
    await agentJson<Connection>("/connections", {
      method: "POST",
      token: session.accessToken,
      // Only postgres is offered. A `web` connection is accepted at creation but fails at run
      // time, which would leave someone holding a connection that can never answer anything.
      body: { name: parsed.data.name, kind: "postgres", secret: { dsn: parsed.data.dsn } },
      // Creating a connection opens a real socket to the customer's database, which is slower
      // than a plain read.
      timeoutMs: 20_000,
    });
  } catch (error) {
    const api = error as ApiError;
    // The agent runs a real SELECT 1 before it stores anything, so a 400 here means the
    // credentials do not work. That belongs on the field, not in a page-level banner.
    if (api.status === 400) {
      return { fieldErrors: { dsn: api.message } };
    }
    return { message: api.message ?? "Could not add that connection." };
  }

  revalidatePath("/connections");
  revalidatePath("/ask");
  return {};
}

const TableNames = z.array(z.string().min(1).max(200)).max(1000);

/** What a refresh changed, so the confirmation can say so rather than only "done". */
export type RefreshState = FormState & { added?: string[]; removed?: string[] };

/** The tables page, the cards that count its tables, and the composer that checks them. */
function revalidateTables(connectionId: string) {
  revalidatePath(`/connections/${connectionId}/tables`);
  revalidatePath("/connections");
  revalidatePath("/ask");
}

export async function saveTableSelection(
  connectionId: string,
  tables: string[],
): Promise<FormState> {
  const session = await getSession();
  if (!session) return { message: "Your session has ended. Sign in again." };

  const parsed = TableNames.safeParse(tables);
  if (!parsed.success) return { message: "That list of tables could not be read." };

  try {
    await agentJson<ConnectionTables>(
      `/connections/${encodeURIComponent(connectionId)}/tables`,
      {
        method: "PUT",
        token: session.accessToken,
        body: { tables: parsed.data },
        // Saving reads the chosen tables' structure from the customer's database first.
        timeoutMs: 20_000,
      },
    );
  } catch (error) {
    const api = error as ApiError;
    return { message: api.message ?? "Could not save that choice." };
  }

  revalidateTables(connectionId);
  return {};
}

export async function refreshTables(connectionId: string): Promise<RefreshState> {
  const session = await getSession();
  if (!session) return { message: "Your session has ended. Sign in again." };

  let result: TablesRefresh;
  try {
    result = await agentJson<TablesRefresh>(
      `/connections/${encodeURIComponent(connectionId)}/tables/refresh`,
      { method: "POST", token: session.accessToken, timeoutMs: 20_000 },
    );
  } catch (error) {
    const api = error as ApiError;
    return { message: api.message ?? "Could not refresh the tables." };
  }

  revalidateTables(connectionId);
  return { added: result.added, removed: result.removed };
}

export async function deleteConnection(connectionId: string): Promise<FormState> {
  const session = await getSession();
  if (!session) return { message: "Your session has ended. Sign in again." };

  try {
    await agentJson(`/connections/${encodeURIComponent(connectionId)}`, {
      method: "DELETE",
      token: session.accessToken,
    });
  } catch (error) {
    const api = error as ApiError;
    return { message: api.message ?? "Could not remove that connection." };
  }

  revalidatePath("/connections");
  revalidatePath("/ask");
  return {};
}
