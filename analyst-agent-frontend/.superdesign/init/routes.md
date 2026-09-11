# Routes

File-based routing, Next.js App Router. No `src/` directory — `app/` sits at the repo
root. Two route groups: `(app)` for the authenticated product, `(auth)` for sign-in.

## Pages

| URL | File | Layout | What it renders |
|---|---|---|---|
| `/` | `app/page.tsx` | root | Server `redirect("/ask")`. Nothing else. |
| `/ask` | `app/(app)/ask/page.tsx` | `(app)` | **The main screen.** Mints one `randomUUID()` threadId per conversation so follow-ups replay earlier turns, fetches connections straight from the agent, renders `AskWorkspace`. Filters out `kind === "web"` connections. |
| `/connections` | `app/(app)/connections/page.tsx` | `(app)` | Ruled list of databases plus an add form. Centred `max-w-3xl`. Shows a `border-l-2 border-fault` notice when the agent is unreachable. |
| `/runs` | `app/(app)/runs/page.tsx` | `(app)` | Run history, 50 per page, keyset cursor. Centred `max-w-4xl`. Titled "History". Results are not stored — only the question, query and answer. |
| `/login` | `app/(auth)/login/page.tsx` | `(auth)` | Sign in. Carries `?next=` through to the action. `searchParams` is awaited (Next 16). |
| `/register` | `app/(auth)/register/page.tsx` | `(auth)` | Sign up. Creates a tenant; the user becomes its owner. |

Every `(app)` page sets `export const dynamic = "force-dynamic"` and calls
`requireSession(<path>)` before rendering.

Each of `(app)/ask`, `(app)/connections`, `(app)/runs` has a `loading.tsx` that renders
only the word "Loading" in mono.

## Page copy (verbatim, for reproduction fidelity)

- `/connections` h1 "Connections" · sub "The databases you can ask about. Questions are answered by reading them, never by writing to them."
- `/runs` h1 "History" · sub "Everything this organisation has asked. Results are not stored, so open a run to see the query and the answer, then ask it again for fresh numbers."
- `/login` h1 "Sign in" · sub "Ask your database a question in plain English." · footer "No account yet? Create one"
- `/register` h1 "Create an account" · sub "You will be the owner of a new organisation. Teammates can join later." · footer "Already have an account? Sign in"

Heading scale in use: `text-[1.5rem] font-normal` on the `(app)` pages,
`text-[1.625rem] font-medium` on the `(auth)` pages. Sub-copy is
`text-[0.9375rem] text-ink-muted` with `max-w-[58ch]`.

## Route handlers

| Route | File | Purpose |
|---|---|---|
| `POST /api/runs` | `app/api/runs/route.ts` | **SSE stream.** Proxies bytes through untouched, `maxDuration = 120`, opens with a `: open` comment so headers flush immediately. |
| `GET /api/runs` | same | History page, keyset cursor. |
| `GET /api/runs/[runId]` | `app/api/runs/[runId]/route.ts` | One run's detail. |
| `/api/connections` | `app/api/connections/route.ts` | List and create. |
| `/api/auth/refresh` | `app/api/auth/refresh/route.ts` | The only place a document navigation can get rotated cookies written. `safeNext()` guards open redirects. |

## Proxy (Next 16's middleware)

`proxy.ts` at the repo root exports a `proxy` function, not `middleware`. It is an
**optimistic cookie check only** and never calls the network. `/api` is deliberately
excluded from the matcher, because a matched path buffers the request body and that
would break the SSE stream. Prefetch requests are skipped via `missing:` headers.

The real authorisation gate is `lib/auth/dal.ts`, not the proxy.
