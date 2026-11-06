# Design system (UI/UX audit, Nov 2026)

Source of truth: `web/src/system.css` (tokens + primitive styles, loaded last) and `web/src/ui.tsx` / `web/src/components.tsx` (primitives). New UI must use these tokens; legacy rules in `styles.css` keep working and are migrated when touched.

## Tokens

| Group | Tokens | Rule |
| --- | --- | --- |
| Type (6 sizes) | `--text-xs` 12 · `--text-sm` 13 · `--text-base` 14 · `--text-md` 16 · `--text-lg` 20 · `--text-xl` 28 | No half-pixel sizes in new code. |
| Spacing | `--space-1…10` (4–40 px, existing) | Multiples of 4. |
| Radius | `--r-sm` 6 · `--r-md` 10 · `--r-pill` | Cards `--r-md`, tags `--r-pill`. |
| Neutral text | `--ink` · `--muted` · `--subtle` · `--tertiary` (raised to #8b95a8 for 4.5:1) | Body text never below `--subtle`. |
| Status | `--c-success` · `--c-warning` · `--c-danger` · `--c-info` · `--c-neutral` | Always paired with an icon or words. |
| Provenance | `--c-automated` · `--c-proposal` · `--c-human` · `--c-ai` | Dashed border = not a decision (proposal, AI). |
| Focus | `--focus-ring` | Applied to every `:focus-visible`. |

No gradients, glow or decorative motion in new components; primary buttons lost their glow.

## Primitives

| Primitive | Where | Use |
| --- | --- | --- |
| `ProvenanceTag kind=automated\|proposal\|human\|ai` | `ui.tsx` | Every statement that could be mistaken for a conclusion. Shows label + actor + time. |
| `EmptyState` | `ui.tsx` | Lists with no rows; says what to do next. |
| `ProgressBar` | `ui.tsx` | Words first ("12 of 337"), bar second; `role=progressbar`. |
| `Table` (+ `selection`, `label`) | `components.tsx` | Focusable labelled scroll region; optional checkbox column for bulk actions. |
| `Drawer` | `components.tsx` | Modal with focus trap, Escape, focus return. Used for bulk review. |
| `Mutation` / notices | `components.tsx` | Success = `role=status`, error = `role=alert`. |
| `Field` + `.field-error` | `components.tsx`, `system.css` | Label, optional help, inline error with `aria-describedby`. |
| `Badge`, `TierBadge` | `components.tsx`, `charts.tsx` | Severity always carries text. |

## Patterns

- **AI vs human:** automated signal → `automated`; agent/MCP proposal → `proposal` (never counts as a decision); human-review credential → `human` with signer and time; assistant answer → `ai` with model or "computed from the run, no AI".
- **Bulk actions:** select → preview (counts by severity, first items) → explicit confirm naming the signer → per-item progress → per-item results with retry of failures.
- **Immutable data:** frozen runs show "Frozen snapshot", never a live indicator.

## Typography (standardised to the landing page)

One family everywhere: **Outfit** (self-hosted via `@fontsource/outfit`, weights 300–800). Monospace (**JetBrains Mono**) only for technical text and the eyebrow kicker, as on the landing page. Cinzel removed.

| Token | Value | Use |
|---|---|---|
| `--font-sans` / `--sans` / `--display` | Outfit | All UI text and headings |
| `--font-mono` / `--mono` | JetBrains Mono | Hashes, IDs, JSON, code, tool names, timestamps, eyebrow kicker |
| `--fw-regular/medium/semibold/bold/display` | 400/500/600/700/800 | Body / labels, nav / section headings, buttons / page headings / hero |
| `--lh-tight/heading/body` | 1.1 / 1.2 / 1.55 | Hero / headings / body |
| `--tracking-tight` | -0.01em | Headings |
| `--tracking-label` | 0.08em | Uppercase labels (table headers, metric labels, field names) |

Hierarchy: hero 800 (landing, login), page `h1` 700, section `h2` 600, card headings 500–600, body 400, labels 500 uppercase with `--tracking-label`. Use `.tag.tag-mono` when a pill shows a hash.
