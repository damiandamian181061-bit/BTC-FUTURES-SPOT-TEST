# frontend: the dashboard web app

Vite + React + TypeScript. It shows the paper-trading dashboard: signals, strategy B, strategy A, the combined result,
the kill switches and the run history. It is read-only: it never talks to Binance and never places orders.

## Where the numbers come from

1. **The API** (`GET /api/dashboard`), which computes everything live from the paper logs. In Docker the API serves
   this app on the same origin; in development Vite proxies `/api` to `http://127.0.0.1:8000`.
2. **Fallback:** `data/dashboard.json`, the file the 23:10 UTC scheduled task writes. The header shows "live" or
   "from file" so you know which one you are looking at.

The app re-reads its data every minute. `src/types.ts` mirrors the JSON (schema 1, `payload()` in
`backend/src/btc_bot/reporting/dashboard.py`).

## Run it

Everything at once, from the project root: `docker compose up -d --build`, then open http://127.0.0.1:8000.

For front-end work with hot reload (Windows PowerShell or WSL; Node 24):

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173 ; double-clicking dev.cmd does the same on Windows
```
Start the API too (`docker compose up -d` or `btc-bot api`) for live numbers; without it the app shows the file.

```bash
npm run build        # type-check + bundle into dist/ (also copies dashboard.json into dist/data/)
```

## Layout

```
src/App.tsx                     header (nav, refresh, theme), section order, loading and error states
src/api.ts                      useDashboard(): API first, file fallback, polling
src/types.ts                    TypeScript mirror of the dashboard JSON
src/format.ts, src/theme.ts     number/date formatting; Auto/Light/Dark theme
src/components/                 SignalBar, StrategyB, StrategyA, Combined, KillSwitches, Operations, EquityChart, ui
src/styles.css                  design tokens and layout
vite.config.ts                  /api proxy, /data dev middleware, vendor chunks
```

## Conventions

- Series colours: paper = blue, expected = grey dashed, buy & hold = orange, in every chart. The pair passes the
  data-viz palette validator in light and dark mode.
- Status is never colour alone: badges carry an icon and a word.
- Numbers are computed in Python; the front end only formats them. Add a number in `payload()`, mirror it in
  `src/types.ts`, render it in the matching component.
