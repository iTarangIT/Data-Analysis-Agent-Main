# Page dependency trees

Traced recursively through local imports only (`@/…`, `./…`); node_modules skipped.
Every file below is under 200 lines, so **all of them can be passed whole as
`--context-file`** — no line-ranging is needed anywhere in this repo. The largest is
`ask-workspace.tsx` at 190 lines and `app/globals.css` at 184.

---

## `/ask` — the main screen
Entry: `app/(app)/ask/page.tsx`

```
app/(app)/ask/page.tsx
├── components/ask/ask-workspace.tsx          (190)  "use client" — transcript + composer
│   ├── components/ask/run-timeline.tsx        (77)  the stage spine
│   │   ├── features/ask/run-types.ts
│   │   └── lib/utils.ts
│   ├── components/ask/sql-block.tsx           (41)  <pre> + hover-reveal copy
│   ├── components/ask/result-table.tsx        (88)  hand-built grid, sticky header
│   │   ├── features/ask/cells.ts             (58)  cell rendering, string-safe
│   │   ├── features/ask/run-types.ts
│   │   └── lib/utils.ts
│   ├── components/ask/run-error.tsx           (41)  error code -> recovery sentence
│   │   └── features/ask/run-types.ts
│   ├── components/ui/button.tsx
│   ├── features/ask/use-run.ts               (104)  React binding
│   │   ├── lib/sse/sse-stream.ts
│   │   ├── features/ask/run-machine.ts       (164)  pure reducer, no React
│   │   └── features/ask/run-types.ts
│   └── lib/api/types.ts
├── lib/api/agent-client.ts
├── lib/api/types.ts
└── lib/auth/dal.ts
```

Layout chain: `app/layout.tsx` -> `app/(app)/layout.tsx` -> `components/app-shell/app-shell.tsx` -> `components/app-shell/nav-link.tsx`

**The composer's `<textarea>` and `<select>` are raw elements, not the shadcn
`Textarea`/`Select` primitives.** They are styled inline to sit on ground.
Cmd/Ctrl+Enter submits.

**Known gap:** the SSE contract carries a `chart` event, `lib/api/types.ts` defines
`ChartSpec`, and `run-machine.ts` stores it — but **nothing renders it.**

---

## `/connections`
Entry: `app/(app)/connections/page.tsx`

```
app/(app)/connections/page.tsx
├── components/connections/connection-form.tsx (99)  submit IS the connection test
│   ├── actions/connections.ts
│   ├── actions/auth.ts
│   └── components/ui/{button,input,label}.tsx
├── components/connections/connection-list.tsx (92)  ruled list, inline delete confirm
│   ├── actions/connections.ts
│   ├── components/ui/button.tsx
│   └── lib/api/types.ts
├── lib/api/agent-client.ts
├── lib/api/types.ts
└── lib/auth/dal.ts
```

Delete confirmation is **inline**, not a dialog. There is no dialog anywhere in the app.

---

## `/runs`
Entry: `app/(app)/runs/page.tsx`

```
app/(app)/runs/page.tsx
├── components/ask/run-history.tsx            (151)  expandable ruled list + cursor paging
│   ├── components/ask/sql-block.tsx
│   ├── components/ui/button.tsx
│   ├── lib/api/types.ts
│   └── lib/utils.ts
├── lib/api/agent-client.ts
├── lib/api/types.ts
└── lib/auth/dal.ts
```

Note `run-history.tsx` lives under `components/ask/`, not a `components/runs/` directory.

---

## `/login` and `/register`
Entry: `app/(auth)/login/page.tsx`, `app/(auth)/register/page.tsx`

```
app/(auth)/{login,register}/page.tsx
├── actions/auth.ts                                  login / register / logout
└── components/auth/auth-form.tsx             (100)  field-driven, useActionState + useFormStatus
    ├── actions/auth.ts
    └── components/ui/{button,input,label}.tsx
```

Layout chain: `app/layout.tsx` -> `app/(auth)/layout.tsx` -> `components/auth/auth-hero.tsx` (55)

`auth-hero.tsx` is a static English-question-to-SQL demo panel on ground, hidden below `lg`.
`auth-form.tsx` is generic: pages pass a `fields` array, `submitLabel`, `pendingLabel`
and an optional `next`. Errors are returned by the action, never thrown.
