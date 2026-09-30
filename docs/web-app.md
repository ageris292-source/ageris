# Aegis web app

The console at `frontend/` is a Next.js 15 app (Tailwind 4, Recharts, lucide
icons) that talks only to the Aegis API. The browser holds a short-lived JWT
in `sessionStorage` and never any provider, broker or alert-channel secret.

## What's in it

| Area | Page | Highlights |
|---|---|---|
| Overview | `/` Dashboard | Greeting, paper equity, qualified-today count, market regime, unread alerts; **watchlist** with sparklines and research stance; top opportunities; recent alerts; execution readiness |
| Research | `/stocks` | Screener: filter, sort by change/price, star to watch, per-row refresh, admin "Add stock" (optionally fetches prices at once) |
| | `/stocks/[ticker]` | Header with price, day change, Watch, Refresh, **Evaluate a trade** (prefills the trade form). Tabs: Overview (interactive chart with SMA/RSI/volume, research summary with composite score ring and per-agent bars, model estimate, bull/bear case, plain-words narrative, key risks, report history), Technical, Fundamentals, News, Valuation & macro, Risk, Data (quality, provenance, corporate actions, runs, admin CSV import). Agent tabs load on first open. |
| | `/ranking` Opportunities | Headline, qualified/all filter, one-click **Propose** (prefills the trade), first-blocking-gate chart, counterfactuals, history |
| | `/backtests` | KPI tiles, growth of ₹1 vs NIFTY 50, calibration scatter, folds, reproducibility, model registry with confirmed activate/retire |
| Trading | `/trade` New trade | Guided proposal with live order value / risk / reward / R:R, cost estimate, the 4-step flow explained, decision view with gate progress bar and "problems only" filter, recent proposals, gate catalogue |
| | `/paper` | KPIs, equity curve, **approval queue** with a confirmation dialog, tabs for positions, theses (stop → entry → target track with the current price), fills and orders |
| | `/portfolios` | KPIs, holdings, sector allocation, limit/advisory checks, risk metrics, what-if fit |
| Operations | `/alerts` | All / unread / critical filters, mark read, delivery-channel status |
| | `/monitoring` (admin) | Per-model drift and calibration, history with drill-down |
| | `/system` | **Kill switch** (halt with reason; admin resume), full readiness checks, infrastructure, live-trading status, engines, data sources, scheduled jobs, macro series (admin refresh / record official figure) |
| | `/users` (admin) | Invite (one-time temporary password with copy buttons), change role, reset password, deactivate/reactivate |
| | `/account` | Profile, change password, theme (light / dark / system), keyboard shortcuts |

Everywhere: ⌘K / Ctrl K (or `/`) opens search over stocks and pages; toasts
confirm every action; destructive or consequential actions ask first; empty,
loading and error states are designed rather than blank; tables collapse
columns on small screens and the sidebar becomes a drawer on phones.

## Design system

* Tokens live in `app/globals.css` as CSS variables with hand-picked light and
  dark sets (`data-theme` on `<html>`, set before first paint so there is no
  flash). Tailwind utilities (`bg-panel`, `text-muted`, `text-pass`…) map to them.
* Primitives are in `components/ui/` (`core.tsx`: Button, Card, Badge, Stat,
  Tabs, Segmented, Field/Input/Select, Table, Callout, EmptyState, Skeleton;
  `Dialog.tsx`; `Status.tsx`: gate/freshness/stance badges and score bars;
  `Sparkline.tsx`).
* Status is never colour alone: every state carries an icon and a word.
* Charts use the validated reference palette (slots 1–3 per theme), thin
  2px lines, dashed secondary series, a legend whenever there is more than one
  series, and hover tooltips.

## Team access

There is still no public sign-up. An admin invites a person on **Users**; Aegis
creates the account with a one-time temporary password, shown once, which the
admin shares privately. At first sign-in the person must choose their own
password — every other endpoint answers 403 until they do.

Tokens carry a version number. Changing or resetting a password, changing a
role or deactivating an account bumps it, so older sessions stop working at
once. An admin cannot demote or deactivate themselves, and the last active
admin can never be removed.

## Local development

```bash
# API (see README for Postgres/Redis)
cd backend && uvicorn app.main:app --reload
# Web
cd frontend && npm install && NEXT_PUBLIC_AEGIS_API_URL=http://localhost:8000 npm run dev
npm run typecheck && npm run build
```
