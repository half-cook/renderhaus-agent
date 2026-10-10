# Design System

The rules that keep every surface — the production canvas, the marketing/landing
page, the auth screens, and anything built after this doc — reading as one
product instead of a collection of separately-styled pages. Each section
below documents a real, already-shipped convention (with the file it lives
in) rather than a new one invented for this doc. Where a category has no
shipped example yet (tables, today), that's said plainly instead of
inventing one.

The tokens themselves live in code, not here — `app/globals.css`'s `:root`
and `@theme` blocks. This doc is the reading of those tokens: what each one
means, when to reach for it, and which existing component to copy instead of
writing new CSS.

## Color

Every color is a semantic CSS custom property, never a hardcoded hex, so
dark/light and future themes come from one place. Defined once in
`app/globals.css`:

| Token | Dark (`:root`) | Light (`:root[data-theme="light"]`) | Use for |
|---|---|---|---|
| `--bg` | neutral-950 | stone-100 | Page/canvas background |
| `--chrome` | neutral-900 | `#fff` | Header/toolbar chrome |
| `--node` | neutral-900 | `#fff` | Card/node/panel surfaces |
| `--line` | neutral-800 | stone-300 | Borders, hover fills |
| `--grid` | neutral-600 | stone-400 | Canvas dot grid only — deliberately not tied to `--line`, so dots stay visible against borders instead of blending in |
| `--text` | neutral-100 | stone-900 | Primary text |
| `--muted` | neutral-500 | stone-500 | Secondary text, idle icons, idle connector lines |
| `--active` | neutral-100 | stone-900 | Selected/focused state, primary button ink |
| `--selected` | indigo-400 | indigo-500 | Selected node/frame border only — reuses the image-port/"running"-status indigo, not a new hue |
| `--accent` | amber-400 | amber-500 | Spend/credit UI only — not a general interactive accent |
| `--danger` / `--ok` / `--warn` | red/emerald/amber-400 | red/emerald/amber-500 | Error / success / warning states |

Light mode uses Tailwind's **stone** scale, not **neutral** — a warm ivory
page background with brighter white cards on top, matching Claude.ai's
console rather than a flat single white.

Two more fixed palettes, referenced by id rather than resolved per-theme
because they're identity, not state:

- **Port colors** (`--color-port-image/video/audio/text`): fixed hues so a
  socket reads the same regardless of theme — indigo/teal/pink/neutral.
  Referenced from the handle, the edge, and the node-tag icon; if you touch
  one, touch all three.
- **Status colors** (`--color-status-queued/running/succeeded/failed`):
  neutral/indigo/emerald/red, driving both the status dot and its label.

**The marketing/landing page is a deliberate, scoped exception** —
`app/(marketing)/page.module.css` defines its own local `--l-ink`/`--l-muted`/
`--l-line`/`--l-bg` and stays light regardless of the visitor's theme
preference (`color-scheme: light` on `.landing`). It's a sales surface, not
the tool, and reads as one deliberate look rather than adapting to a device
setting. These tokens are local to `.landing` and never leak out; don't reuse
`--l-*` outside that page, and don't let `.landing` styles reference `--bg`/
`--text`/etc.

## Shape & elevation

- **`--radius: 0` everywhere.** Sharp corners across every node, panel,
  popover, button, and chip (SSENSE-style editorial minimalism) — one token
  drives it. The exception is intentional: **circular indicators stay
  round** (`border-radius: 999px`) — status dots, port dots, the chrome-dot
  traffic lights — because there the shape *is* the meaning (a dot), not
  decoration. The marketing page's buttons hardcode `border-radius: 0`
  directly for the same rule, since that page doesn't consume `var(--radius)`.
- **`--shadow: none`.** No drop shadows on cards/panels. The one exception is
  the marketing page's demo-panel frame (`box-shadow: 0 40px 80px -40px …`),
  explicitly called out in that file's own comment as a deliberate exception
  so the embedded demo reads as "a window onto the real product" sitting on
  a page, not more page chrome.
- **Borders are always `1px solid var(--line)`**, brightening only on a
  meaningful state change — selection (`var(--selected)`) or focus
  (`var(--active)`), never on plain hover (hover changes background instead,
  see Buttons below).

## Motion

- **`--ease: cubic-bezier(0.32, 0.72, 0, 1)`** — the one easing curve for
  every transition (buttons, node borders, panel open/close). Don't
  introduce a second easing curve without a reason.
- **160ms** is the standard transition duration for hover/active/selection
  state changes (`.icon-btn`, `.text-btn`, `.flow-node` border/shadow, the
  landing page's CTA opacity). Longer, purposeful animations (panel
  slide-ins, loading states) aren't bound to this — 160ms is specifically
  the "a state just changed" duration.

## Typography

Base stack: `var(--font-geist)` (body/UI), `var(--font-geist-mono)`
(monospace, where used), `var(--font-pixel)` (Silkscreen — wordmark only,
illegible at paragraph sizes by design, never body text).

Two distinct label conventions exist for two distinct jobs — use the one
that matches what you're labeling, don't invent a third:

- **Eyebrow / section label** — small, uppercase, letter-spaced, muted:
  11px, `text-transform: uppercase`, `letter-spacing` in the 0.04em–0.14em
  range, `color: var(--muted)`. This is `label.field > span` (form field
  captions), the landing demo's node headers ("PROMPT", "RESULT"), the
  header nav (`.text-btn`), and the wordmark. Use for: a caption identifying
  *what kind of thing* something is, not its identity.
- **Node title** — sentence case, not uppercase: 12px, weight 500 (600 for
  the numeric badge), `color: var(--muted)` idle → `var(--active)` selected
  (`.node-tag-name`/`.node-tag-badge`, `app/globals.css`). Use for: a
  user-editable *name*, e.g. a specific node's title.
- **Headline** — the marketing page's only true heading style: 22px, weight
  700, `letter-spacing: -0.01em`, sentence case (`.landing-eyebrow h1`).
  Scoped to that page; the product itself has no marketing-style headline
  today.

## Buttons

All button variants share one base rule block (`app/globals.css`, the
`.icon-btn, .text-btn, .rail-btn, .queue-chip, .send-btn, .generate,
.generate-lg` selector group): no border, transparent background, `color:
var(--text)`, and the standard 160ms/`--ease` transition. Variants layer on
top of that shared base:

| Class | Shape | Use for |
|---|---|---|
| `.icon-btn` | 32×32, centered icon | A single icon-only action |
| `.rail-btn` | 36×36, centered icon | Tool-rail buttons specifically |
| `.text-btn` | 28px tall, 10px h-padding, 13px/500, `var(--muted)`→`var(--text)` on hover | An icon+label or label-only inline action (nav links, "Sign in") |
| `.generate` / `.generate-lg` | Full-width, `background: var(--text)`, `color: var(--bg)`, 14px/600 | The one *filled/primary* button — inverted (ink-colored fill, background-colored text) rather than an accent hue, since `--active` (not a hue) is this system's primary-action color |

State rules, consistent across all of them: hover → `background:
var(--line)` (never a color shift on the icon/text itself); active → `scale
(0.98)`; disabled → `opacity: 0.4` + `cursor: default`. Focus uses the global
`:focus-visible` rule (`outline: 2px solid var(--active)`), not a
button-specific style.

## Surfaces / cards

The node card is the one card pattern in the product (`.flow-node`,
`app/globals.css`): `background: var(--node)`, `border: 1px solid
var(--line)`, `border-radius: var(--radius)`, `box-shadow: var(--shadow)`.
Selected state widens nothing — it only recolors the same 1px border to
`var(--selected)`. Any new panel, popover, or card should start from this
exact rule set rather than a new one; `.node-toolbar` and the landing demo's
node cards already do.

## Backgrounds

A flat `var(--bg)` fill reads as a generic, empty page — anywhere a
full-page background is needed, prefer the canvas's own dot-grid texture instead
so the surface reads as part of the product rather than a blank form. One
shared rule, `.canvas-texture-bg` (`app/globals.css`): `background-color:
var(--bg)` plus a `radial-gradient(var(--grid) 1.5px, transparent 1.5px)`
dot at `24px` spacing. This matches, exactly, the real canvas's own
`<Background variant={BackgroundVariant.Dots} gap={24} size={1.5}
color="var(--grid)" />` (`components/canvas/StudioCanvas.tsx`) and the
landing demo's `.demo-canvas` — now also used by the sign-in/sign-up pages
(`app/sign-in/[[...sign-in]]/page.tsx`, `app/sign-up/[[...sign-up]]/page.tsx`)
instead of a flat fill. Reach for `.canvas-texture-bg` on any new full-page
surface rather than redeclaring the gradient locally.

## Ports & connectors

A connector is always a **smooth bezier curve** — never a straight line,
never right-angle/orthogonal routing — leaving each block tangent to its
edge before bending toward the other. Stroke `var(--muted)` idle /
`var(--active)` selected-or-focused, `1.5px`, solid, round caps.

Two modes, chosen by the block shape being connected, not preference:

- **Fixed-port** (typed, multi-socket blocks — the production canvas today):
  each socket gets its own `<Handle>`, pinned to a fixed side — inputs left,
  outputs right, stacked vertically when there's more than one
  (`components/canvas/nodes/BaseNode.tsx`). The side never moves regardless
  of layout, because the side *is* part of the socket's identity. Edges are
  React Flow's own built-in bezier (`defaultEdgeOptions = { type: "default"
  }` in `components/canvas/StudioCanvas.tsx`); line styling is the global
  `.react-flow__edge-path` rule. Ports are also where the fixed port-color
  palette above applies (`.port-image`, `.port-video`, etc.) — a 10px dot,
  `border: 2px solid var(--node)`, one of the exceptions kept circular on
  purpose.
- **Floating-edge** (generic, single-socket blocks — the landing page demo
  today): the connector attaches to whichever side of each block faces the
  other, recomputed live as blocks move, since there's no typed socket
  identity to preserve. Shared geometry lives in
  `studio/lib/canvas/connector-path.ts` (`floatingEdgeConnector` +
  `bezierConnectorPath`) — import it rather than writing new curve math —
  styled with the global `.connector-path` class in `app/globals.css`, kept
  numerically in sync with `.react-flow__edge-path` by hand (React Flow
  requires its own literal class name, so the two can't share one rule).

**Don't** make fixed ports "floating" without reopening this doc first — it
would break the left=input/right=output convention the multi-port canvas
relies on to be readable.

## Tables

No table exists in the product yet — this section exists so the first one
follows the system instead of inventing its own look. When one is needed,
build it from the tokens already established above rather than a new
pattern: row/header background `var(--node)` or `var(--bg)`, `1px solid
var(--line)` row dividers, `var(--radius)` (0) corners, no `box-shadow`,
header labels in the eyebrow style (11px, uppercase, `var(--muted)`), body
text in the standard 13–14px UI sizes used elsewhere in this doc, and a
selected-row treatment that recolors a `var(--line)`-weight border to
`var(--selected)` rather than adding a shadow or changing radius. If an
actual table ships, replace this paragraph with real class names and a file
reference, the way every other section here does.

## Adding something new

Before writing new CSS for a button, card, label, or connector: check
whether one of the patterns above already covers it. If it's genuinely new
(a component category not listed here), add a section to this doc in the
same style — cite the real file and class name, don't describe a rule that
isn't shipped yet — rather than letting a one-off style live undocumented in
a component's own CSS module.


## Tailwind token bridge

`app/globals.css` maps Studio variables into Tailwind v4 with `@theme inline`.
Use `bg-background`, `text-foreground`, `border-border`, and the direct Studio
colors (`bg-chrome`, `text-muted`, `border-selected`). The existing port and
status colors keep their names and hues. Amber `accent` remains for spend and
credits only. Menu hover uses `chrome` or `line`, never `accent`.

The cascade order is `theme, base, xyflow, legacy, components, utilities`.
The xyflow import belongs to its own layer before Studio's legacy rules.
Existing CSS modules also declare this order and belong to `legacy`, preserving
their original specificity and order against global overrides. Next can load a
module before globals, so each module must declare the order first. Utilities win
normal declarations. Important declarations reverse the layer order.
Keep third-party CSS out of the unlayered cascade when Studio overrides it.
Clerk's appearance remains as shipped.

Tailwind's radius and shadow scales are reset with `--radius-*: initial` and
`--shadow-*: initial`. Square and flat is the default. The only named radius
utility is `rounded-pill` (9999px), reserved for status chips, a toolbar capsule,
and avatars. Existing screens retain their shipped shapes. Do not use
`rounded-full`, numeric or arbitrary radii, or shadow utilities for new UI.

Use semantic tokens, no `dark:` utilities. In CSS modules use `var(--token)`,
never `@apply`. Fonts are `font-sans` (Geist), `font-mono` (Geist Mono), and
`font-silkscreen` (Silkscreen, wordmark only). The preflight mono fallback stays
unchanged so existing unstyled keyboard hints keep their font. Icons remain Lucide.
`duration-base` uses `--duration-base: 160ms`; `ease-studio` uses the existing
`--ease` curve. Hover, focus, and state changes stay on these CSS tokens.
Motion's `m` components live under the unmounted `MotionProvider` with
`LazyMotion`/`domAnimation` and user reduced-motion settings. No new spring
or easing token is introduced. Never animate xyflow node wrappers.

Portals reuse the existing z-index scale: flow 1, controls 5, inspector 25,
rail 30, header 40, menu 50. Use `z-(--z-menu)` for overlay content and
`z-(--z-header)` for a dialog backdrop. Do not invent larger magic numbers.
A portal from a scoped theme must target a container inside that scope
with its `container` prop, or it inherits the document theme instead.

## Opt-in dark beta palette

`[data-surface="beta"]` overrides the same semantic variables and declares
`color-scheme: dark`, including inside a light-theme app or on the document root.
The root selector matches the light-theme selector's specificity. The near-black
background (#090909), chrome (#111110), warm charcoal card (#191918), and
border (#30302c) frame ivory text (#f5f5ef) with secondary text (#a3a39a).
Amber remains reserved for spend and credits. Port and status identity colors
stay inherited. The token parity test guards every root variable.
No existing page opts in. The current marketing page keeps its scoped light
palette until its design is approved.

## Copy rules (standing product rule)

Product UI, the marketing page, toasts and error text never show the platform
fee (no "Platform fee" line, no percentage, no fee footer) and never name the
underlying providers or models. Approval cards show one fee-inclusive price per
step plus a total; line items describe the work ("Product still", "10-second
clip", "Voiceover"), not the vendor. The only allowed mention is a quiet FAQ
line: "Every price you see includes a small platform fee." Fee and provider
fields stay backend-only; client payload strings and errors must not carry them.
Screenshot demo data follows the same rule, and the capture kit fails when
visible text, `title`, `aria-label`, `alt` or `placeholder` leaks either.
