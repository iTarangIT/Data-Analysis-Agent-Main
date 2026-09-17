# analyst-agent-frontend

The product shell for the analyst agent: sign in, connect a Postgres database, ask it a
question in plain English, and watch it write the SQL, run it, and explain the result.

Next.js 16 (App Router, no `src/`), React 19, Tailwind v4, TypeScript strict.

## Running it

The agent must be running first, on port 8000. From `../analyst-agent-backend`:

```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Then here:

```bash
npm install
cp .env.example .env.local   # AGENT_API_URL, and the Supabase project's URL and publishable key
npm run dev
```

Signing in needs the Supabase project set up once, in its dashboard:

- **Authentication → URL Configuration**: Site URL `http://localhost:3000`, and
  `http://localhost:3000/api/auth/**` on the redirect allow list.
- **Authentication → Emails → Confirm signup**: link to
  `{{ .SiteURL }}/api/auth/confirm?token_hash={{ .TokenHash }}&type=email`, so the link works in
  any browser rather than only the one that signed up.
- **Authentication → Sign In / Providers → Google**: enabled, with the client ID and secret of a
  Google Cloud "Web application" OAuth client whose redirect URI is
  `https://<project-ref>.supabase.co/auth/v1/callback`.

```bash
npm test        # vitest
npm run build   # also type-checks
npx eslint .
```

One thing that will catch you out: the agent's integration suite shares the local App DB and
truncates `users`, `tenants`, `connections` and `runs` between tests. Running `pytest` over
there therefore deletes your organisation and the connections you added. You stay signed in to
Supabase, so the app sends you to `/welcome` to name a new one, but the data is gone.

## How it is put together

**The browser never holds a token.** It talks only to this app; this app talks to the agent and
to Supabase. Supabase Auth owns sign-in, sessions and refresh, but only ever from the server:
there is no browser Supabase client and no `NEXT_PUBLIC_` variable, so its session cookies are
written httpOnly. Exactly one module (`lib/api/agent-client.ts`, marked `server-only`) attaches
the Supabase access token as an `Authorization` header, and the agent verifies it itself.

**Signing in and belonging are separate.** Supabase says who someone is; the agent says which
organisation they belong to, and answers `403 onboarding_required` until they have one. A
first-time Google user names theirs on `/welcome`. An email sign-up names it on the form, and
`/api/auth/confirm` creates it when the confirmation link is opened (`lib/auth/landing.ts`).

**`proxy.ts` is what Next 15 called `middleware.ts`.** Next 16 renamed the file and the
export, and its runtime is Node and cannot be configured. It verifies the session with
`getClaims()` (locally, against the project's cached public keys) and redirects a signed-out
navigation; prefetches are excluded. It is not the gate. `lib/auth/dal.ts` is, and every server
component, server action and route handler calls it, because a server action is reachable by
a direct POST and not only through the form that renders it.

**Refreshing a session happens in the proxy.** Cookies cannot be written from a server
component, or after a response starts streaming, so `lib/supabase/proxy.ts` refreshes an
expired token before the page renders and writes the new cookies onto both the request and the
response. Route handlers under `/api`, which the proxy skips, refresh for themselves through
`lib/supabase/server.ts`. Supabase tolerates the brief overlap when two of them race.

## Two things that will bite anyone touching the stream

**The agent's frames end with CRLF.** `sse-starlette` sets `DEFAULT_SEPARATOR = "\r\n"`, so a
decoder that splits the buffer on two newlines matches nothing, emits no events, and leaves
the UI waiting on a stream that is arriving perfectly well. `lib/sse/sse-frame.ts` normalises
first, and holds back a trailing carriage return rather than normalising each chunk alone,
because a chunk boundary landing between the `\r` and the `\n` otherwise invents a frame break
mid-frame. Its test drives it at every chunk size from one byte up, which is how that second
bug was found.

**Response headers do not flush until the first chunk.** `app/api/runs/route.ts` therefore
opens with a `: open` SSE comment. Without it the browser's `fetch` promise does not settle
until the agent's first event, which looks exactly like a broken parser.

## Two rules the run state machine encodes

`features/ask/run-machine.ts` is a pure reducer with no React, so every path can be driven as
an array in a test.

- **Stages go backwards.** When the guard rejects a query the agent writes another one, so
  `sql_gen` follows `sql_guard`. Anything that renders the stages as a fixed ladder will lie
  on exactly the runs worth looking at.
- **A stream that ends without `done` or `error` is a failure.** Treating it as success is how
  a truncated run gets presented as a complete answer. This is also what a serverless timeout
  looks like, which is why this app needs to run as a long-lived Node process: a run can take
  forty seconds, and a platform that deploys route handlers as short-lived functions will cut
  it off.

## One rule the result table encodes

The agent serialises with `json.dumps(default=str)`, so ints, floats and booleans survive as
themselves while `Decimal`, `date`, `datetime` and `UUID` arrive as **strings**. A money column
comes through as `"266300.00"`. Nothing in `components/ask/result-table.tsx` calls `Number()`
on a cell, because in an analytics product that ships a wrong figure with total confidence.

## Design

Light throughout, and built from one card. `--bg` is the page, `--surface` is a card sitting
on it, `--surface-sunk` is anything recessed into a card. Separation is a hairline plus a
shadow faint enough to read as a lift rather than a drop.

`--brand` is the one accent: it marks the primary action and the machine working, and nothing
else. `--fault`, `--warning` and `--success` mark states and are never decoration.
`--code-bg` is the only dark surface in the product and exists because SQL is the one thing
here people read as code. There is no dark theme and no theme toggle -- `@custom-variant dark`
in `app/globals.css` deliberately redefines the variant as a class nothing sets, so registry
components' `dark:` utilities stay inert rather than flipping the app on someone's OS setting.

Tokens live in `app/globals.css` and are re-exported as utilities through `@theme inline`.
Chart series are capped at three steps of one hue; `MAX_SERIES` in `features/ask/chart.ts` is
the enforcement, not the palette.

Typefaces are Inter and JetBrains Mono. Mono is not decoration here: it carries the SQL, the
result-table cells, the figures and the wordmark, all of which genuinely are monospace
content. The wordmark is the literal lowercase word `analyst` -- there is no logo file, no
mark and no monogram.

Navigation is a left rail. It used to be a top rail, on the argument that a column would steal
width from a result table that can be five hundred columns wide; `min-w-0` on the main column
is what answers that, by letting the table scroll inside its own box instead of stretching the
flex row. Remove it and the old objection becomes correct again.

## shadcn/ui

`components.json` and `lib/utils.ts` were written by hand and `shadcn init` was never run,
which is what avoids its long-standing Tailwind v4 detection failure. Add primitives with
`npx shadcn@latest add <name>`, then check the `cn` import: the CLI has been emitting
`from "cn"` instead of `from "@/lib/utils"`.

`components/ui/` is registry output. Composition belongs in `components/ask/`,
`components/connections/` and `components/app-shell/`, because `add` overwrites on re-run.
