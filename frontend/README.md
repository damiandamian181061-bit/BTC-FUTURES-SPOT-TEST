# frontend/ : the paper-trading dashboard app

Vite + React + TypeScript. It renders `data/paper/dashboard.json`, which `code/dashboard.py` writes (by hand or by the
23:10 UTC scheduled task). The app is read-only: it never talks to Binance and never places orders.

```
frontend/
  index.html, src/main.tsx      entry
  src/App.tsx                   header (nav, refresh, theme), section order, loading / error states
  src/api.ts                    useDashboard(): fetches data/dashboard.json, re-reads it every minute
  src/types.ts                  TypeScript mirror of the JSON (schema 1, see payload() in code/dashboard.py)
  src/format.ts                 number / date formatting
  src/theme.ts                  light / dark / system toggle (localStorage)
  src/components/ui.tsx         Badge (status + icon), Tile, Section, DataTable, statusClass()
  src/components/EquityChart.tsx Recharts line chart: paper vs expected vs buy & hold, crosshair tooltip
  src/components/SignalBar.tsx, StrategyB.tsx, StrategyA.tsx, Combined.tsx, KillSwitches.tsx, Operations.tsx
  src/styles.css                tokens (reference data-viz palette, validated for both themes) and layout
  vite.config.ts                dev plugin that serves ../data/paper at /data; vendor chunking
  scripts/copy-data.mjs         after `vite build`, copies dashboard.json into dist/data/
  dev.cmd                       double-click to start the dev server on Windows
```

## Run it (Windows PowerShell or a double-click; Node 24 is installed on the laptop)

```powershell
cd "C:\Users\damia\Documents\BTC Strategy Project\frontend"
npm install          # once
npm run dev          # http://127.0.0.1:5173  (or double-click dev.cmd)
```
The dev server reads the live `data/paper/dashboard.json`; refresh the data with `python3 code/dashboard.py` in WSL and
the page picks it up within a minute (or press Refresh).

```powershell
npm run build        # type-check + bundle into dist/, then copies dashboard.json into dist/data/
npm run preview      # serves dist/ for a look
```
`dist/` is a self-contained static site (relative paths) that any static server can host. It shows the JSON that was
copied at build time, so rebuild (or copy a newer `dashboard.json` into `dist/data/`) to update it.

## Changing the numbers

The front end formats; it does not compute. Add a number to `payload()` in `code/dashboard.py`, mirror it in
`src/types.ts`, render it in the matching component. `code/test_dashboard.py` (class `T4_json`) checks the payload is
JSON-safe and complete.

## Conventions

- Series colours: paper = blue (`--series-1`), expected = grey dashed, buy & hold = orange (`--series-2`) in every chart.
  The pair passes the data-viz palette validator in light and dark mode; the dark steps are selected, not auto-flipped.
- Status is never colour alone: badges carry an icon and a word.
- Every chart has a legend when it shows more than one series, a crosshair tooltip listing every series, and the same
  numbers in a table on the page.
