> **Historical.** This file records the system as it was before the redesign to the
> reference mockups. The palette, typefaces, utility names and top-rail navigation it
> describes no longer exist in the code. `.superdesign/design-system.md` is the current
> spec; this is kept only for the reasoning behind decisions that were later reversed.

# Theme — "Read-only"

## Part 1 — Compact token summary

Tailwind **v4, CSS-first**. No `tailwind.config.*` exists. Everything below is defined
in `app/globals.css` and re-exported as utilities through `@theme inline`.

### Organising idea

The product only ever reads, and the interface says so by staying quiet. The agent's
workspace is dark (`ground`); every artifact it hands back -- the SQL, the result table,
the written answer -- is printed on paper (`paper`), which is also where dense tabular
data reads best.

Two semantic colours only. `live` marks the machine working and nothing else. **Never
put `live` on a button.**

### Palette

| Token | Value | Role |
|---|---|---|
| `--ground` | `#131922` | chrome base (dark) |
| `--ground-raised` | `#1a222d` | raised chrome surface |
| `--ground-ink` | `#e7eaee` | text on ground |
| `--ground-muted` | `#8b97a6` | secondary text on ground; also `--ring` |
| `--rule-ground` | `#252b33` | hairline on ground |
| `--paper` | `#fbfbf9` | artifact base (light) |
| `--paper-sunk` | `#f2f2ee` | recessed paper surface |
| `--ink` | `#1a1f26` | text on paper |
| `--ink-muted` | `#676f7b` | secondary text on paper |
| `--rule-paper` | `#d8dad5` | hairline on paper; also `--border` / `--input` |
| `--live` | `#0fb5ae` | machine working. signal, not brand. never a button |
| `--fault` | `#c2554d` | errors |

Those map onto the shadcn primitive names (`--background`, `--primary`, `--border`,
`--ring`, ...) so a registry component lands on paper by default.

`.on-ground` re-points the *same* primitive variables at the dark palette. There is no
second palette and no `.dark` class in use.

### Utilities produced

`bg-ground` `bg-ground-raised` `text-ground-ink` `text-ground-muted` `border-rule-ground`
`bg-paper` `bg-paper-sunk` `text-ink` `text-ink-muted` `border-rule-paper`
`text-live` `bg-live` `text-fault` `bg-fault` plus the full shadcn primitive set.

### Type

Fonts: **IBM Plex Sans** and **IBM Plex Mono**, via `next/font/google` in `app/layout.tsx`,
exposed as `--font-plex-sans` / `--font-plex-mono` and wired to `--font-sans` / `--font-mono`.
Mono is load-bearing, not decorative: it carries SQL and result-table cells.

**The screens do not use Tailwind's type scale.** They use arbitrary rem values
throughout: `text-[0.8125rem]`, `text-[0.9375rem]`, `text-[1.5rem]`, `leading-[1.65]`,
`max-w-[58ch]`. Reproductions should match this, not substitute `text-sm` / `text-base`.

### Radius

`--radius: 0.375rem`. Derived: `--radius-sm` = radius - 2px, `--radius-md` = radius,
`--radius-lg` = radius + 2px.

### Shadows

**None.** The design system defines no shadow tokens and the screens use no elevation.
Separation is done with hairline rules (`border-rule-paper` / `border-rule-ground`).
Do not introduce shadows or layered glows.

### Breakpoints

Tailwind defaults. The only structural breakpoint in use is `lg`, where the auth hero
appears; below `lg` the auth screens are form-only.

### Motion

Exactly one non-user-triggered animation: `.is-live`, a 1.4s opacity pulse (1 -> 0.35)
on the stage spine while the agent works. It stops the moment the run settles. A full
`prefers-reduced-motion: reduce` block kills all animation and transition durations.
There is no animation library installed -- no framer-motion, no GSAP.

### Focus and selection

`:focus-visible` is a 2px solid `--ring` outline at 2px offset. Because the shell
inverts `--ring` with everything else, one rule covers both surfaces.
`::selection` is `--live` at 28% in oklab.

---

## Part 2 — Raw source

### `app/globals.css`

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

/* ---------------------------------------------------------------------------
   Read-only

   The product only ever reads. Three independent layers in the backend enforce
   that, and the interface says the same thing by staying quiet.

   The organising idea: the agent's workspace is dark, and what it hands you is
   printed on paper. Chrome sits on `ground`. Every artifact the agent produces
   -- the SQL, the result table, the written answer -- sits on `paper`, which is
   also where dense tabular data reads best.

   Two semantic colours only. `live` marks the machine working and nothing else,
   which is what keeps it a signal rather than a brand colour. Never put it on a
   button.
--------------------------------------------------------------------------- */

:root {
  --ground: #131922;
  --ground-raised: #1a222d;
  --ground-ink: #e7eaee;
  --ground-muted: #8b97a6;
  --rule-ground: #252b33;

  --paper: #fbfbf9;
  --paper-sunk: #f2f2ee;
  --ink: #1a1f26;
  --ink-muted: #676f7b;
  --rule-paper: #d8dad5;

  --live: #0fb5ae;
  --fault: #c2554d;

  --radius: 0.375rem;

  /* shadcn primitives read these. Mapped onto the palette above so an
     out-of-the-box component lands on paper and already looks like the rest. */
  --background: var(--paper);
  --foreground: var(--ink);
  --card: var(--paper);
  --card-foreground: var(--ink);
  --popover: var(--paper);
  --popover-foreground: var(--ink);
  --primary: var(--ground);
  --primary-foreground: var(--paper);
  --secondary: var(--paper-sunk);
  --secondary-foreground: var(--ink);
  --muted: var(--paper-sunk);
  --muted-foreground: var(--ink-muted);
  --accent: var(--paper-sunk);
  --accent-foreground: var(--ink);
  --destructive: var(--fault);
  --destructive-foreground: var(--paper);
  --border: var(--rule-paper);
  --input: var(--rule-paper);
  --ring: var(--ground-muted);
}

/* The shell inverts the same tokens rather than defining a second palette, so
   the two surfaces can never drift apart. */
.on-ground {
  --background: var(--ground);
  --foreground: var(--ground-ink);
  --card: var(--ground-raised);
  --card-foreground: var(--ground-ink);
  --popover: var(--ground-raised);
  --popover-foreground: var(--ground-ink);
  --primary: var(--paper);
  --primary-foreground: var(--ground);
  --secondary: var(--ground-raised);
  --secondary-foreground: var(--ground-ink);
  --muted: var(--ground-raised);
  --muted-foreground: var(--ground-muted);
  --accent: var(--ground-raised);
  --accent-foreground: var(--ground-ink);
  --border: var(--rule-ground);
  --input: var(--rule-ground);
  --ring: var(--ground-muted);
}

@theme inline {
  --color-ground: var(--ground);
  --color-ground-raised: var(--ground-raised);
  --color-ground-ink: var(--ground-ink);
  --color-ground-muted: var(--ground-muted);
  --color-rule-ground: var(--rule-ground);

  --color-paper: var(--paper);
  --color-paper-sunk: var(--paper-sunk);
  --color-ink: var(--ink);
  --color-ink-muted: var(--ink-muted);
  --color-rule-paper: var(--rule-paper);

  --color-live: var(--live);
  --color-fault: var(--fault);

  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  /* IBM Plex, one superfamily drawn for technical contexts. Mono carries the
     SQL and the table cells, which genuinely are monospace content. */
  --font-sans: var(--font-plex-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-plex-mono), ui-monospace, "SF Mono", monospace;

  --radius-sm: calc(var(--radius) - 2px);
  --radius-md: var(--radius);
  --radius-lg: calc(var(--radius) + 2px);
}

@layer base {
  * {
    border-color: var(--border);
  }

  body {
    background: var(--background);
    color: var(--foreground);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
  }

  /* Visible, and on the right surface either way. The shell inverts --ring
     along with everything else, so this needs no second rule. */
  :focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }

  ::selection {
    background: color-mix(in oklab, var(--live) 28%, transparent);
  }
}

/* The one piece of non-user-triggered motion in the product: the stage spine
   ticking as the agent works. It answers the machine's action, and it stops the
   moment the run settles. */
@keyframes pulse-live {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

.is-live {
  animation: pulse-live 1.4s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .is-live {
    animation: none;
  }

  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

### `app/layout.tsx` (font wiring)

```tsx
import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { Toaster } from "@/components/ui/sonner";

import "./globals.css";

// One superfamily, drawn for technical contexts. Mono is not decoration here: it carries the
// SQL and the table cells, which genuinely are monospace content.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Analyst",
  description: "Ask your database a question in plain English and watch it answer.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable} h-full`}>
      {/* Extensions inject attributes onto body before React hydrates, which is not a
          mismatch we can fix or should report. */}
      <body className="flex min-h-full flex-col" suppressHydrationWarning>
        {children}
        <Toaster position="bottom-right" />
      </body>
    </html>
  );
}
```

### `components.json`

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "app/globals.css",
    "baseColor": "zinc",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "ui": "@/components/ui",
    "utils": "@/lib/utils",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "iconLibrary": "lucide"
}
```

### `postcss.config.mjs`

```js
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
```
