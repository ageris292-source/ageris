# Aegis web app

The console at `frontend/` is a Next.js 15 app (Tailwind 4, Recharts, lucide
icons) that talks only to the Aegis API. The browser holds a short-lived JWT
in `sessionStorage` and never any provider, broker or alert-channel secret.

## What's in it

| Area | Page | Highlights |
|---|---|---|
| Overview | `/` Dashboard | Greeting, paper equity, qualified-today count, market regime, unread alerts; **named watchlists** (switch lists, create/rename/delete) with sparklines and research stance; top opportunities; recent alerts; execution readiness |
| Research | `/stocks` | Screener: filter, sort by change/price, star to watch, per-row refresh, admin "Add stock" (optionally fetches prices at once) |
| | `/stocks/[ticker]` | Header with price, day change, Watch, Refresh, **Evaluate a trade** (prefills the trade form). Tabs: Overview (interactive chart with SMA/RSI/volume, research summary with composite score ring and per-agent bars, model estimate, bull/bear case, plain-words narrative, key risks, report history), Technical, Fundamentals, News, Valuation & macro, Risk, Data (quality, provenance, corporate actions, runs, admin CSV import), **Notes & alerts** (which of your lists hold it, your price alerts, your journal notes). Agent tabs load on first open. |
| | `/compare` | Up to 3 stocks side by side: price indexed to 100 on the first common session (chart or table), return, annualised volatility, max drawdown, research stance/score/confidence, latest-FY ratios. Shareable URL (`?t=A,B,C`) |
| | `/ranking` Opportunities | Headline, qualified/all filter, one-click **Propose** (prefills the trade), first-blocking-gate chart, counterfactuals, history |
| | `/backtests` | KPI tiles, growth of ₹1 vs NIFTY 50, calibration scatter, folds, reproducibility, model registry with confirmed activate/retire |
| Trading | `/trade` New trade | Guided proposal with live order value / risk / reward / R:R, cost estimate, the 4-step flow explained, decision view with gate progress bar and "problems only" filter, recent proposals, gate catalogue |
| | `/paper` | KPIs, equity curve, **approval queue** with a confirmation dialog, tabs for positions, **performance** (win rate, profit factor, avg win/loss, max drawdown, total return, portfolio vs NIFTY 50 indexed chart, realised P&L by stock, CSV downloads), theses (stop → entry → target track with the current price), fills (with a Journal button per fill) and orders |
| | `/journal` | Private research notes and trade journal (note / entry reason / exit reason / review), optional link to a stock or paper order, tags, search, type and tag filters, CSV export |
| | `/portfolios` | KPIs, holdings, sector allocation, limit/advisory checks, risk metrics, what-if fit |
| Operations | `/alerts` | Inbox (all / unread / critical, mark read, "Just you" badge on personal alerts, delivery-channel status) and **My price alerts** (create, pause, delete, check now) |
| | `/activity` | Read-only view of the append-only audit trail with plain-English labels, action-group filter, load older, CSV export. Admins see everyone (or only themselves); analysts see only their own |
| | `/monitoring` (admin) | Per-model drift and calibration, history with drill-down |
| | `/system` | **Kill switch** (halt with reason; admin resume), full readiness checks, infrastructure, live-trading status, engines, data sources, scheduled jobs, macro series (admin refresh / record official figure) |
| | `/users` (admin) | Invite (one-time temporary password with copy buttons), change role, reset password, deactivate/reactivate |
| | `/account` | Profile, change password, **sign-in activity** (recent sign-ins and failed attempts with IP and device) and **sign out everywhere**, theme, **your data** CSV downloads, keyboard shortcuts |
| Help | `/help` | Getting-started steps, searchable FAQ, glossary, links to policies, "Show welcome guide" |
| | `/legal` | Risk disclaimer, terms of use and privacy (readable before sign-in) |

Everywhere: ⌘K / Ctrl K (or `/`) opens search over stocks and pages; toasts
confirm every action; destructive or consequential actions ask first; empty,
loading and error states are designed rather than blank; tables collapse
columns on small screens and the sidebar becomes a bottom tab bar on phones.

Also: a five-step **welcome guide** on first sign-in (per user, per device), a
friendly 404 and error pages, and an **offline screen** for the installed app
(a service worker that caches only `offline.html` and an icon — pages and API
data are never cached, so stale numbers are never shown).

## Price alerts

Personal rules on one stock: close above / below a price, a daily rise or fall
of at least X %, or RSI(14) above / below a level. The Celery beat job
`aegis.check_price_alerts` runs after each price refresh (12:15 and 14:15 UTC,
Mon–Fri); **Check now** runs the same check for your own rules.

* Each rule is evaluated at most once per stored session.
* Only fresh data is used: if the stock's freshness is not PASS the rule is
  reported as "not checked" and never fires (UNKNOWN never passes).
* Missing inputs (e.g. too little history for RSI) are reported, never guessed.
* One-shot rules switch off after firing; repeating rules re-arm only after the
  condition clears.
* A fired rule creates a **personal** in-app alert (only its owner sees it);
  "High importance" rules use severity *warning*, so they are also pushed to
  Telegram / email when those team channels are configured.
* Alerts inform only. Nothing here proposes or places an order.

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
  series, and hover tooltips. Multi-series line charts (compare, performance)
  also label each line's end and are capped at three series, because the
  palette's fourth slot fails the all-pairs legibility floor.

## Team access

There is still no public sign-up. An admin invites a person on **Users**; Aegis
creates the account with a one-time temporary password, shown once, which the
admin shares privately. At first sign-in the person must choose their own
password — every other endpoint answers 403 until they do.

Tokens carry a version number. Changing or resetting a password, changing a
role or deactivating an account bumps it, so older sessions stop working at
once. An admin cannot demote or deactivate themselves, and the last active
admin can never be removed.

## API added for these features

| Endpoint | Purpose |
|---|---|
| `GET/POST /watchlists`, `PATCH/DELETE /watchlists/{id}` | Named lists (max 20; at least one is kept) |
| `GET /watchlist?list_id=`, `POST /watchlist {ticker, list_id?}`, `DELETE /watchlist/{ticker}?list_id=`, `GET /watchlist/membership/{ticker}` | Items; no `list_id` = your first list (backwards compatible) |
| `GET/POST /price-alerts`, `PATCH/DELETE /price-alerts/{id}`, `POST /price-alerts/check` | Price rules (max 50 active) |
| `GET/POST /journal`, `PATCH/DELETE /journal/{id}` | Private entries; filters `ticker`, `kind`, `order_id`, `tag`, `q` |
| `GET /activity`, `GET /activity/summary` | Audit trail, scoped by role |
| `GET /auth/sessions`, `POST /auth/logout-all` | Your sign-in history; end every session (returns a fresh token) |
| `GET /export/{orders,fills,positions,equity,watchlist,journal,price-alerts,activity}.csv` | CSV downloads (formula-injection safe; missing = empty cell) |
| `GET /paper/portfolios/{id}/performance` | Scorecard and benchmark comparison |

Alerts gained an optional owner (`alerts.user_id`): team alerts have none and
everyone sees them; personal alerts are visible only to their owner. Migration
`0015_user_features` moves each user's existing watchlist into a list named
"My watchlist".

## Phones and tablets

The app is built for phones first and is checked at 320, 360 and 390 px wide,
on iPhone and Android, and on tablets in landscape.

- **Navigation.** Below 1024 px a bottom tab bar replaces the sidebar. It holds
  Home, Stocks, Ideas and Paper. A **More** sheet holds every other section,
  plus your account, theme, trading status and sign out.
- **Lists instead of wide tables.** On phones, tables become tappable rows
  (`MobileList` / `MobileItem`), and the full table appears from 640 px up.
- **Touch.** Controls are at least 44 px tall. Inputs use 16 px text, so iOS
  never zooms in on focus.
- **Dialogs.** Dialogs open as bottom sheets, with full-width buttons.
- **Notches.** The layout respects the notch and home-indicator areas
  (`viewport-fit=cover` plus safe-area insets).
- **Charts.** Charts get shorter and use narrower axes on phones.
- **Install.** It is installable as an app: a web manifest, home-screen icons
  and an Apple touch icon. In Safari choose Share → Add to Home Screen; in
  Chrome choose Install app.

## Local development

```bash
# API (see README for Postgres/Redis)
cd backend && uvicorn app.main:app --reload
# Web
cd frontend && npm install && NEXT_PUBLIC_AEGIS_API_URL=http://localhost:8000 npm run dev
npm run typecheck && npm run build
```
