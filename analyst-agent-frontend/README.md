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
cp .env.example .env.local   # AGENT_API_URL points at the agent
npm run dev
```

```bash
npm test        # vitest
npm run build   # also type-checks
npx eslint .
```

One thing that will catch you out: the agent's integration suite shares the local App DB and
truncates `users`, `tenants`, `connections` and `runs` between tests. Running `pytest` over
there therefore signs you out here and deletes the connections you added. The app handles it
without complaint, but the data is gone.

## How it is put together

**The browser never holds a token.** It talks only to this app; this app talks to the agent.
The access and refresh tokens live in httpOnly cookies, and exactly one module
(`lib/api/agent-client.ts`, marked `server-only`) attaches an `Authorization` header. Nothing
here knows the agent's origin except the server.

**`proxy.ts` is what Next 15 called `middleware.ts`.** Next 16 renamed the file and the
export, and its runtime is Node and cannot be configured. It reads the session cookie and
redirects; it never calls the network and never keeps module state, because it runs on every
navigation including prefetches. It is not the gate. `lib/auth/dal.ts` is, and every server
component, server action and route handler calls it, because a server action is reachable by
a direct POST and not only through the form that renders it.

**Rotating a token needs a route handler.** Cookies cannot be written from a server component,
or after a response starts streaming. So the proxy hands a stale session to
`/api/auth/refresh`, which rotates, writes the pair, and sends the person on. Concurrent
requests are collapsed into one upstream call, but that only holds inside a single process;
the real protection against a rotation race is the agent's own grace window.

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
