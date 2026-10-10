# Studio UI revamp foundation

The existing screens keep their design. The foundation adds semantic Tailwind
v4 tokens, an opt-in dark beta palette, five Radix adapters, a Sonner wrapper,
a lean MotionProvider, and a manual screenshot kit. The
[design system](../studio/design/DESIGN_SYSTEM.md) remains the source of truth.

## Run design captures

From `studio/`, run `npm ci` and `npm run shots:install` once.
`npm run shots:after` builds the production app, starts an owned Next server on
`localhost:5191`, captures at 1920x1200, and stops that server even on failure.
`npm run shots` is the same capture. `npm run shots:before` sets the before label.
For a baseline checkout, set `SHOT_STUDIO_DIR` to its `studio/` directory and
`SHOT_PORT=5190`. Keep its sibling `configs/` directory.

Set `SHOT_THEME=light` for the second theme. Set `SHOT_OUT_DIR` to an absolute
path to keep evidence outside the repo. Run `npm run shots:compare -- dark`
and `npm run shots:compare -- light` to produce HTML and JSON reports plus
diff images. `SHOT_SKIP_BUILD=1` reuses a production build that you have
already built without Clerk keys. The default rebuild avoids stale code.

The kit's development dependencies live in Studio's package.json. Its own
package.json only marks its TypeScript tests as ES modules; it has no separate
install. Studio TypeScript excludes `design-shots/`. CI does not run browsers.
`npm run shots:a11y` runs optional axe checks with the same mock fixtures and
privacy guard. Existing accessibility findings are reported, not hidden.

Canned fixtures show only Demo Studio and Demo Creator. Every unmatched API
request is aborted, and non-fixture mutations are blocked. The runner sets both
Clerk keys empty and points backend rewrites at a closed local port. Auth
screens require Clerk and are skipped. Beta screens have no implementation
and are skipped. Optional HAR recordings stay ignored and must be scrubbed.
Screenshots are mock design evidence, not the Comet E2E required by AGENTS.md.

## Add a Radix adapter by hand

1. Read the pinned design system and the Radix shadcn component documentation.
2. Inspect the new-york-v4 registry source in a scratch directory with
   `npx shadcn@latest view https://ui.shadcn.com/r/styles/new-york-v4/<name>.json`.
   Do not run `shadcn init` in Studio.
3. Copy only the needed file into `components/ui/`. Import the single
   `radix-ui` package, Lucide, and `@/lib/cn`. React imports are type-only.
4. Replace colors with Studio tokens. Remove shadows, stock radii, `dark:`
   overrides, and stock animation classes. Use `data-slot` attributes.
   Keep `DialogTitle`, keyboard focus, Escape handling, and Radix composition.
5. Reuse `--z-menu` and pass a scoped portal `container` for beta content.
   Add `nodrag nopan` to triggers inside canvas nodes.
6. Run the Node contracts, TypeScript, production build, and affected captures.

Toaster and MotionProvider are intentionally unmounted. Mount Toaster once in
the root when a feature uses it. Wrap Motion `m` components in MotionProvider.
No animation is added to existing screens. `tw-animate-css` is omitted because
these adapters use no animate-in/out classes. No components.json is added.

## Keep these constraints

Do not add the full shadcn kit, Storybook, cmdk, Vaul, next-themes,
framer-motion as a direct dependency, Base UI, React Aria, Phosphor,
tailwindcss-animate, Sass, Next 16, or a React upgrade beyond 19.2.x.
Motion internally depends on framer-motion; use only `motion/react` in app code.
The pinned stack is Next 15.5.23, React 19.2.8, and Tailwind 4.3.3.

Existing CSS modules declare the full layer order before `@layer legacy` and
use `var(--token)`, never `@apply`. Next may load a module before globals.
New UI uses semantic colors,
no `dark:` utilities. Amber is for spend and credits. Default shapes are square
and flat. Only `rounded-pill` is allowed for the documented pill cases.
State changes use `duration-base ease-studio`. Never animate xyflow node
wrappers. The layer order is `theme, base, xyflow, legacy, components, utilities`.
Important declarations reverse this order. Do not reintroduce an unlayered
xyflow import. Clerk appearance stays as shipped pending a screen design.

`next/font/google` needs network at build time. npm and Playwright caches may
need writable paths through `npm_config_cache` and `PLAYWRIGHT_BROWSERS_PATH`
in restricted environments. Never use another process's development port or
stop a process the kit did not start.
