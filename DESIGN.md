---
name: FinResearch Agent
description: Reproducible financial research and backtesting dashboard
colors:
  bg: "oklch(1 0 0)"
  surface: "oklch(0.975 0.004 250)"
  surface-strong: "oklch(0.94 0.007 250)"
  ink: "oklch(0.18 0.018 250)"
  muted: "oklch(0.42 0.014 250)"
  primary-crimson: "oklch(0.58 0.16 31)"
  primary-crimson-deep: "oklch(0.42 0.13 31)"
  accent-teal: "oklch(0.48 0.12 185)"
  warning-amber: "oklch(0.72 0.14 78)"
  danger-red: "oklch(0.58 0.17 28)"
typography:
  headline:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontWeight: 650
    lineHeight: 1.22
    letterSpacing: "0"
  title:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontWeight: 620
    lineHeight: 1.3
    letterSpacing: "0"
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.58
    letterSpacing: "0"
  label:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 520
    lineHeight: 1.45
    letterSpacing: "0"
rounded:
  sm: "4px"
  md: "6px"
  lg: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary-crimson}"
    textColor: "{colors.bg}"
    rounded: "{rounded.md}"
  app-header:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.ink}"
  status-quality:
    backgroundColor: "{colors.accent-teal}"
    textColor: "{colors.bg}"
  warning:
    backgroundColor: "{colors.warning-amber}"
    textColor: "{colors.ink}"
---

# Design System: FinResearch Agent

## 1. Overview

**Creative North Star: "The Research Audit Desk"**

FinResearch Agent should feel like a financial research desk built for audit,
replication, and careful interpretation. The interface is bright, high-contrast, and
quietly disciplined: the surface stays pure white so dense charts, tables, controls,
and caveats remain easy to read, while a warm crimson primary color gives the product
its own identity without borrowing the default fintech blue vocabulary.

The system should use Ant Design as an implementation substrate, not as a brand. Keep
its predictable component behavior, keyboard affordances, forms, tables, and menus, but
retune the theme around FinResearch Agent's own palette, typography, density, and
financial-safety rules.

**Key Characteristics:**
- White research workspace with crisp cool-neutral panels.
- Warm crimson identity used sparingly for primary actions and current context.
- Teal verification color for data quality, validation, and trustworthy completion.
- Compact product typography, never marketing hero scale inside the app.
- Persistent visibility for assumptions, data windows, baselines, costs, and risk limits.

## 2. Colors

The palette is restrained but ownable: primary crimson carries identity, cool neutrals
carry the workspace, and teal carries research-quality confidence.

### Primary
- **Audit Crimson** (`oklch(0.58 0.16 31)`): primary actions, selected context, and
  decisive workflow progression. Use white text on filled crimson surfaces.
- **Deep Audit Crimson** (`oklch(0.42 0.13 31)`): hover, pressed, and high-emphasis
  states where the normal primary needs more contrast.

### Secondary
- **Verification Teal** (`oklch(0.48 0.12 185)`): data-quality pass states,
  validation markers, trustworthy completion, and chart annotations related to
  coverage or integrity.
- **Caution Amber** (`oklch(0.72 0.14 78)`): limitations, missing data, cost warnings,
  and non-blocking risk notices.
- **Risk Red** (`oklch(0.58 0.17 28)`): destructive actions, failed runs, and hard
  errors. Do not use it for positive price movement unless the chart legend makes that
  convention explicit.

### Neutral
- **Pure Workspace** (`oklch(1 0 0)`): body background and main working canvas.
- **Cool Panel** (`oklch(0.975 0.004 250)`): subtle page bands, table hover, and
  low-emphasis grouping.
- **Panel Edge** (`oklch(0.94 0.007 250)`): borders, dividers, table rules, and
  disabled backgrounds.
- **Research Ink** (`oklch(0.18 0.018 250)`): body text and key labels.
- **Muted Ink** (`oklch(0.42 0.014 250)`): secondary copy; never use below 4.5:1 for
  body-sized text.

### Named Rules

**The Evidence Color Rule.** Crimson means user intent. Teal means evidence quality.
Amber means caveat. Red means failure or destructive risk. Do not blur these roles.

## 3. Typography

**Display Font:** Inter or system sans-serif fallback.
**Body Font:** Inter or system sans-serif fallback.
**Label/Mono Font:** no dedicated mono font unless code, IDs, or parameter hashes need it.

**Character:** Typography is compact, measured, and research-oriented. It should help
users scan controls, metrics, and caveats quickly without slipping into brokerage or
marketing tone.

### Hierarchy
- **Headline** (650, 24-28px, 1.22): page titles and major workflow headings.
- **Title** (620, 16-20px, 1.3): panel titles, card titles, chart group headings.
- **Body** (400, 14px, 1.58): forms, tables, alerts, explanatory copy, and empty states.
- **Label** (520, 13px, 1.45): filters, segmented controls, legends, status labels, and
  dense metadata.

### Named Rules

**The App Typography Rule.** Keep the product in a fixed rem scale. No fluid display
headlines, tracked all-caps eyebrow scaffolds, or oversized marketing numerals in the
authenticated dashboard.

## 4. Elevation

Depth should come from crisp borders, tonal separation, and fixed layout structure.
Shadows are reserved for popovers, dropdowns, and modals where elevation communicates
stacking and focus. Default panels, cards, tables, and chart containers stay flat.

### Shadow Vocabulary
- **Overlay Shadow** (`0 6px 16px rgba(0, 0, 0, 0.12)`): Ant Design dropdowns, popovers,
  and modal surfaces only.

### Named Rules

**The Audit Surface Rule.** Working surfaces should feel printable and inspectable. If a
shadow is not communicating an overlay relationship, remove it.

## 5. Components

### Buttons
- **Shape:** precise small radius (`6px`), never pill-shaped unless used for compact tags.
- **Primary:** Audit Crimson fill with white text; use for the main action on a surface.
- **Hover / Focus:** deepen to Deep Audit Crimson; add a visible focus ring using a pale
  crimson outline rather than a decorative glow.
- **Secondary / Ghost:** white or Cool Panel background with Panel Edge border and
  Research Ink text.

### Chips
- **Style:** compact status chips with 4px radius and semantic color roles.
- **State:** teal for verified/complete, amber for caveat, red for failed/destructive,
  cool neutral for inactive metadata.

### Cards / Containers
- **Corner Style:** 6px for regular cards, 10px for larger analysis panels.
- **Background:** Pure Workspace for primary work areas; Cool Panel for secondary bands.
- **Shadow Strategy:** flat at rest; use borders and dividers for structure.
- **Internal Padding:** 16px for dense cards, 24px for chart and backtest panels.

### Inputs / Fields
- **Style:** Ant Design controls rethemed with Research Ink text, Panel Edge borders, and
  crimson focus/selected states.
- **Focus:** visible 2px focus ring or Ant-compatible outline; never remove focus styles.
- **Error / Disabled:** field-level errors in Risk Red, disabled backgrounds in Panel Edge.

### Navigation
- **Style:** light sticky top bar with a disciplined product title, route navigation,
  language switcher, and account controls. Use crimson for active route indicators rather
  than a dark default header.
- **Mobile Treatment:** collapse navigation into a menu before controls wrap incoherently;
  keep language and auth access reachable.

### Charts

Charts should prioritize interpretation over decoration. Use labels, legends, line style,
and position alongside color. Backtests must surface gross/net, benchmark, drawdown, data
window, universe, and transaction-cost assumptions near the visualization.

## 6. Do's and Don'ts

### Do:
- **Do** use the palette roles consistently: crimson for intent, teal for evidence, amber
  for caveat, red for failure.
- **Do** keep risk disclaimers, assumptions, and limitations close to backtest and agent
  outputs.
- **Do** make tables, filters, and charts dense but calm, with clear dividers and stable
  control sizes.
- **Do** verify English and Simplified Chinese strings in the actual components before
  shipping.
- **Do** show data windows, universes, sources, baselines, and cost sensitivity wherever
  research conclusions appear.

### Don't:
- **Don't** preserve Ant Design's default navy/blue identity as the product brand.
- **Don't** make the product look like a brokerage, trading terminal cosplay, crypto
  exchange, casino, or signal-selling page.
- **Don't** use hype copy about beating the market, guaranteed returns, buy/sell advice,
  or profitable strategies.
- **Don't** use purple-blue gradient SaaS tropes, glassmorphism, decorative chart colors,
  side-stripe borders, gradient text, or oversized hero metrics.
- **Don't** hide warnings, limitations, failed states, or data-quality gaps behind hover
  interactions.
