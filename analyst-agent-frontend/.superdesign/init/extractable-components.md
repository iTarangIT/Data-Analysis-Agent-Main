> **Historical.** This file records the system as it was before the redesign to the
> reference mockups. The palette, typefaces, utility names and top-rail navigation it
> describes no longer exist in the code. `.superdesign/design-system.md` is the current
> spec; this is kept only for the reasoning behind decisions that were later reversed.

# Extractable components

Only layout components are worth extracting as reusable `<sd-component>` templates.
The shared UI primitives here (`Button`, `Input`, `Label`) are small enough that inline
HTML in a draft is clearer than a component round trip.

---

## 1. `AppShell` — **extract this one**

Source: `components/app-shell/app-shell.tsx` (60 lines)
Appears on: `/ask`, `/connections`, `/runs` — every authenticated page.

The whole chrome of the product. A **3.5rem (`h-14`) top rail, not a sidebar**. The
reason is in the source comment: this app has three places to be, and a nav column
would take horizontal room from a table that can be five hundred columns wide.

Structure, left to right:

| Slot | Content | Classes |
|---|---|---|
| wordmark | the literal lowercase word `analyst`, linking to `/ask` | `font-mono text-sm tracking-tight text-ground-ink` |
| nav | `Ask` · `Connections` · `History` | `flex items-center gap-1` |
| spacer | | `ml-auto` |
| tenant | `user.tenant_name`, hidden below `sm` | `text-[0.8125rem] text-ground-muted` |
| sign out | ghost button in a `<form action={logout}>` | `h-8 px-2 text-[0.8125rem] text-ground-muted` |

Outer wrapper: `flex min-h-dvh flex-col bg-ground`.
Header: `on-ground flex h-14 shrink-0 items-center gap-6 border-b border-rule-ground px-5`.
Children wrapper: `flex min-h-0 flex-1 flex-col`.

Suggested props:

```json
[
  {"name": "activeItem", "type": "string", "defaultValue": "ask"},
  {"name": "tenantName", "type": "string", "defaultValue": "Acme Logistics"}
]
```

React props today: `{ user: User | null; children: React.ReactNode }`.
`user.tenant_name` is the only field the shell reads.

---

## 2. `NavLink` — fold into AppShell, do not extract separately

Source: `components/app-shell/nav-link.tsx` (27 lines)

Too small to stand alone, but its **active treatment is load-bearing and must be
reproduced exactly**: the current section is marked by an *underline*, never a filled
pill, so the rail stays quiet.

- active: `text-ground-ink underline decoration-ground-muted underline-offset-[6px]`
- idle: `text-ground-muted hover:text-ground-ink`
- both: `rounded-sm px-2.5 py-1.5 text-[0.8125rem] transition-colors`
- active is computed as `pathname === href || pathname.startsWith(href + "/")`
- carries `aria-current="page"` when active

---

## Not extractable

- **`AuthHero`** (`components/auth/auth-hero.tsx`, 55 lines) — appears only on the two
  auth routes and is a static content panel, so a draft can inline it.
- **`Button` / `Input` / `Label`** — primitives, better inline. Note that call sites
  override height and colour heavily, e.g. `className="h-8 bg-paper px-4 text-[0.8125rem] text-ground"`.
- **Everything under `components/ask/`, `components/connections/`** — page-specific.

## Brand assets

There is **no logo file**. The wordmark is the literal lowercase text `analyst` set in
IBM Plex Mono. `public/` holds only the unmodified `create-next-app` SVGs
(`next.svg`, `vercel.svg`, `file.svg`, `globe.svg`, `window.svg`), none of which are
referenced by any screen. Do not introduce a logo mark, monogram, or icon where the
real product uses a mono wordmark.
