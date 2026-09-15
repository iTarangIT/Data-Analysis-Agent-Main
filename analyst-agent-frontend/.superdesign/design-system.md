# Design system — "Read-only" (light)

## Product context

An analyst agent. You ask a database a question in plain English; it routes the
question, writes SQL, guards the SQL, executes it read-only, and streams back the
query, the rows and a written answer.

**The product only ever reads.** Three independent layers in the backend enforce that,
and the interface says so out loud rather than by staying quiet: the composer carries a
read-only notice, the connection form hands you the grants that make it true at the
database, and every query the agent ran is shown next to its answer.

### Screens

| Screen | Job |
|---|---|
| `/ask` | Ask, watch the machine work, read the result. The main screen. |
| `/connections` | The databases you can ask about. Add and remove them. |
| `/connections/[id]/tables` | Choose which tables the agent may read, and see what it is shown about them. |
| `/runs` | Everything the organisation has asked, what it spent, and the audit table. |
| `/login`, `/register` | Get in. One organisation per account at registration. |

### Jobs to be done

- Get a number out of a database without knowing SQL, and be able to check the SQL.
- See *what the machine is doing* while it does it, because a run can take 40 seconds.
- Trust that the answer came from the real database and that nothing was written.

---

## What this round changed

The system previously ran a quiet, accent-free, card-free, shadow-free light palette on
IBM Plex behind a top rail. That has been replaced wholesale by the reference design:
an indigo accent, white cards on a grey ground, soft elevation, and a left sidebar.

The idea the old system carried — *chrome is not artifact* — survives, but it is now
expressed by elevation rather than by tone. An artifact is a card that lifts off the
page. Chrome is the flat surface it sits on.

**The app stays light.** There is no dark theme and no theme toggle. The single dark
surface is `--code-bg`, used for SQL and the read-only role script, because code is the
one thing here people read as code.

---

## Colour

| Token | Value | Role |
|---|---|---|
| `--bg` | `#f7f8fa` | the page |
| `--surface` | `#ffffff` | a card on it |
| `--surface-sunk` | `#f1f2f6` | recessed into a card: inputs, chips, table headers |
| `--surface-hover` | `#eceef3` | hover on a sunk surface |
| `--ink` | `#111827` | primary text |
| `--ink-muted` | `#6b7280` | secondary text |
| `--ink-faint` | `#9ca3af` | placeholders, disabled, third-level labels |
| `--line` | `#e5e7eb` | every hairline |
| `--line-strong` | `#d1d5db` | dashed affordances, hollow marks |
| `--brand` | `#5b4be8` | the one accent |
| `--brand-hover` | `#4a3ad4` | its hover |
| `--brand-soft` | `#eeecfd` | active nav pill, avatars, icon tiles |
| `--brand-fg` | `#ffffff` | text on brand |
| `--success` | `#10b981` | tables chosen, read-only confirmed |
| `--warning` | `#f59e0b` | approaching a limit, capped results |
| `--fault` | `#ef4444` | errors and destructive confirmation |
| `--fault-soft` | `#fef2f2` | the ground of an error card |
| `--code-bg` | `#1e1b31` | the only dark surface in the product |
| `--code-fg` | `#e4e4e7` | text on it |

**One accent.** `--brand` marks the primary action and the machine working. It is not a
decorative colour and does not get spent on headings, borders or icons that mean nothing.

Chart series are three steps of one hue: `#5b4be8`, `#8f85f0`, `#c7c1f8`. Three is the
ceiling because a fourth lands below the threshold where full-colour vision separates it
from its neighbour. `MAX_SERIES` in `features/ask/chart.ts` enforces it; past three the
table carries the values instead.

**No dark theme.** `@custom-variant dark (&:is(.dark *))` in `app/globals.css` redefines
the variant as a class nothing ever sets, which is what keeps registry components'
`dark:` utilities inert. Do not remove it as cleanup.

---

## Type

**Inter** and **JetBrains Mono**, loaded via `next/font/google` as variable fonts — no
weight array, because pinning statics ships four files where one does.

Mono is **load-bearing, not decorative**. It carries SQL, result-table cells, figures,
timestamps and the `analyst` wordmark — content that genuinely is monospace. Do not set
headings or body copy in mono for flavour.

Use Tailwind's scale. The one repeated arbitrary pattern is the small-caps label, which
appears on every panel:

```
text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-ink-muted
```

`Eyebrow` in `components/panel.tsx` is that pattern; use it rather than retyping it.

| Use | Value |
|---|---|
| page h1 | `text-2xl font-semibold tracking-tight` |
| card / section title | `text-base font-semibold` or `Eyebrow` |
| body | `text-sm` or `text-[0.9375rem]` |
| figures | `font-mono text-2xl tabular-nums` |
| measure | `max-w-[62ch]` on page copy, `max-w-[68ch]` on answers |

---

## Space, shape, elevation

- Radius `0.5rem` base. Controls are `rounded-md`; cards are `rounded-xl` (0.75rem).
  Only avatars, status badges and the send button are `rounded-full`.
- Two shadows, both faint: `shadow-sm` and `shadow-card`. A card is a hairline **and** a
  shadow; the shadow alone is not enough separation on a near-white ground, and the
  shadow is never used to imply a z-order that does not exist.
- `Panel` in `components/panel.tsx` is the card. Use it rather than retyping the classes.
- Page containers: `max-w-5xl` on `/connections` and `/runs`, `max-w-3xl` on the ask
  transcript, `max-w-[25rem]` on auth. Padding `px-5 py-8 sm:px-8`.
- Sidebar is `w-[212px]`, thread column `w-[248px]`, both `shrink-0`.

---

## Motion

Automatic motion is limited to run feedback: `.is-live` is a 0.9s linear rotation on
the brand-coloured loader asterisk, and the newest answer reveals words at about 30ms
per word, capped at 1.5s after the final text arrives. Earlier answers appear instantly.
The composer has no second spinner, and the process panel's stage marks are static.
A `prefers-reduced-motion: reduce` block disables CSS motion; the typing hook also
observes this preference and immediately reveals the complete available answer.

No animation library is installed. Do not add entrance animations, parallax, scroll
reveals or hover lifts.

---

## Components and patterns that must be preserved

- **The wordmark is the literal lowercase word `analyst` in mono.** There is no logo
  file, no mark and no monogram. The agent's avatar in the transcript is a `Sparkles`
  glyph precisely so that it is not a monogram sneaking back in.
- **Active nav is a filled pill** in `--brand-soft`, the one place that tint is used.
- **Inline confirmation, not dialogs.** Deleting a connection confirms inside its card.
  There is no dialog anywhere in the app.
- **The stage spine keeps repeats.** Stages go backwards when the SQL guard rejects a
  query, so it is a timeline, never a fixed ladder of steps. A hollow mark means real,
  superseded work — never a guess about a stage that has not started.
- **Result tables are hand-built grids** with a sticky header, `max-h-[26rem]` internal
  scroll, and per-column numeric alignment. Nothing calls `Number()` on a cell.
- **`min-w-0` on every flex and grid child that can contain a result table.** Without it
  a five-hundred-column result stretches the layout instead of scrolling inside its box.
  This is what makes a sidebar affordable at all.
- **SQL sits on `--code-bg`** with a copy button that appears on hover.
- **A guessed join looks like a guess.** On the tables screen a relationship inferred from
  matching column names carries a dashed underline and says "inferred" in words; a declared
  key is drawn plain. The difference never rests on the line alone.
- **The table picker never evicts.** At the cap an unticked box is disabled rather than
  letting a new choice push an old one out, and nothing is saved until Save.
- **Errors map a code to a concrete recovery sentence**, not a generic apology.
- **Only what the data supports gets drawn.** The budget bar reads `tokens_last_24h`
  against `daily_token_budget`, both real fields. There is no per-user attribution in the
  audit table because a run carries no actor, and no role badges because every account is
  hardcoded to `owner` with nothing enforced against it.

---

## Accessibility

`:focus-visible` is a 2px solid `--ring` (the brand) outline at 2px offset, everywhere.
`::selection` is brand at 22% in oklab. Active nav carries `aria-current="page"`.
Disabled single sign-on buttons say why they are disabled rather than only looking it.

---

## Hard constraints for generation

Use only the tokens, fonts, spacing, radii and component patterns above. Introduce no
font other than Inter and JetBrains Mono. Introduce no colour outside the tokens listed.
Add no second accent, no gradients, no dialogs, no logo mark, and no dark surface other
than `--code-bg`.
