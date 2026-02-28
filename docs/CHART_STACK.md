# Dashboard chart stack (tech & packages)

## What we use today

| Chart | Package | Tech | Where |
|-------|---------|------|--------|
| **Our candlestick** | **Lightweight Charts** v4.1.0 | **JavaScript** (browser) | `dashboard/js/candlestick.js` |
| **TradingView live** | **TradingView Advanced Chart** (embed) | **JavaScript** (browser, TradingView script) | `dashboard/js/tradingview-embed.js` |
| **P&L / line charts** | **Chart.js** 4.4.1 | **JavaScript** (browser) | `dashboard/js/charts.js` |

- **Backend:** Python (Flask). Serves REST and Socket.IO; it does **not** draw charts.
- **Frontend:** All chart rendering is **client-side JavaScript** in the browser.

---

## “Live” behaviour

- **Our chart (CoinDCX):** Updates when the **exchange sends a candle tick** (current candle OHLC). That is typically every few seconds to a minute for the forming candle, not every second. So it’s “live” in the sense of **candle updates**, not tick‑by‑tick.
- **TradingView tab:** Uses TradingView’s own data feed. You get **real-time, per-tick** style updates and full toolbar (indicators, drawings, volume, etc.) like on their site. Pair is mapped to **BINANCE:XXXUSDT** (e.g. OP → BINANCE:OPUSDT).

Use **“TradingView live”** for second-by-second style live charts; use **“Our chart”** for data coming from your CoinDCX feed.

---

## Confidence on the chart

The line above the chart (e.g. “OP | O: … H: … L: … C: … | Confidence: 87.4%”) now uses the **same** confidence as the Trading Pairs / Quick View: **pair signals’ `signal_strength`**. It no longer shows 0 when the pair has high confidence.

---

## Nginx and Socket.IO

`nginx.conf` has a `location /socket.io/` so the live candle stream reaches the app. Without it, “Our chart” falls back to REST (e.g. every 60s).

---

## If you want a “better” or different chart

- **Same stack (JS in browser):** You can swap or add libraries without changing Python. Options:
  - **TradingView Advanced Charts** (embed) – full TradingView in an iframe; very rich, needs their terms.
  - **ApexCharts** – JS, good for candlesticks and dashboards.
  - **Highcharts** – JS, candlestick/OHLC and many chart types (license for commercial).
  - **Plotly.js** – JS, flexible and open source.
  - **Keep Lightweight Charts** – already TradingView-style, lightweight, and we’ve wired it for live data; improving layout/UX might be enough.
- **Python-rendered charts** (e.g. Matplotlib/Plotly server-side) would require the server to generate images or HTML and are less suitable for **live** interactive charts; the current JS approach is the right one for live.

Summary: **Charts are JS (Lightweight Charts + Chart.js) in the browser.** The candlestick is now set up to be live once nginx is updated and reloaded; if you want a different look or library, we can switch to another **JavaScript** charting lib and keep the same backend.
