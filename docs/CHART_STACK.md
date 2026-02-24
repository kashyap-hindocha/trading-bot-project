# Dashboard chart stack (tech & packages)

## What we use today

| Chart | Package | Tech | Where |
|-------|---------|------|--------|
| **Candlestick (main live chart)** | **Lightweight Charts** (TradingView) v4.1.0 | **JavaScript** (browser) | `dashboard/js/candlestick.js` |
| **P&L / line charts** | **Chart.js** 4.4.1 | **JavaScript** (browser) | `dashboard/js/charts.js` |

- **Backend:** Python (Flask). It does **not** draw charts; it only serves REST (`/api/candles`, etc.) and Socket.IO for live candle stream.
- **Frontend:** HTML + CSS + **JavaScript** in the browser. All chart rendering is **client-side JS**.

So: **chart package = JS (Lightweight Charts + Chart.js), not Python.**

---

## Why the candlestick chart wasn’t “live”

The live stream uses **Socket.IO**. Nginx was only proxying `/api/` to the app, so requests to `/socket.io/` never reached Flask and the chart fell back to REST (e.g. every 60s).  

**Fix applied:** `nginx.conf` now has a `location /socket.io/` that proxies to the same Flask app. After you deploy that and reload nginx, the candlestick chart can use the live stream (and you should see “● LIVE” when connected).

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
