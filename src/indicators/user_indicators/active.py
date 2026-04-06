import numpy as np
import pandas as pd
import talib
from pine2py.executor import Strategy
from pine2py.plotting import plot


class TranslatedStrategy(Strategy):
    def __init__(self, df: pd.DataFrame):
        super().__init__(df)

    def run(self):
        df = self.df
        # pine_line:2 study(title="UT Bot Alerts", overlay = True)
        # pine_line:5 a = input(1,     title = "Key Vaule. 'This changes the sensitivity'")
        # pine_line:6 c = input(10,    title = "ATR Period")
        # pine_line:7 h = input(False, title = "Signals from Heikin Ashi Candles")
        # pine_line:9 xATR = atr(c)
        # pine_line:10 nLoss = a * xATR
        # pine_line:12 src = h ? security(heikinashi(syminfo.tickerid), timeframe.period, df['close'], lookahead = False) : df['close']
        # pine_line:14 xATRTrailingStop = 0.0
        # pine_line:15 xATRTrailingStop := iff(src > nz(xATRTrailingStop[1], 0) and src[1] > nz(xATRTrailingStop[1], 0), max(nz(xATRTrailingStop[1]), src - nLoss),
        # pine_line:16 iff(src < nz(xATRTrailingStop[1], 0) and src[1] < nz(xATRTrailingStop[1], 0), min(nz(xATRTrailingStop[1]), src + nLoss),
        # pine_line:17 iff(src > nz(xATRTrailingStop[1], 0), src - nLoss, src + nLoss)))
        # pine_line:19 pos = 0
        # pine_line:20 pos :=	iff(src[1] < nz(xATRTrailingStop[1], 0) and src > nz(xATRTrailingStop[1], 0), 1,
        # pine_line:21 iff(src[1] > nz(xATRTrailingStop[1], 0) and src < nz(xATRTrailingStop[1], 0), -1, nz(pos[1], 0)))
        # pine_line:23 xcolor = pos == -1 ? color.red: pos == 1 ? color.green : color.blue
        # pine_line:25 ema = ema(src,1)
        # pine_line:26 above = ((ema).shift(1) < (xATRTrailingStop).shift(1)) & ((ema) >= (xATRTrailingStop))
        # pine_line:27 below = ((xATRTrailingStop).shift(1) < (ema).shift(1)) & ((xATRTrailingStop) >= (ema))
        # pine_line:29 buy = src > xATRTrailingStop and above
        # pine_line:30 sell = src < xATRTrailingStop and below
        # pine_line:32 barbuy = src > xATRTrailingStop
        # pine_line:33 barsell = src < xATRTrailingStop
        # pine_line:35 plotshape(buy,  title = "Buy",  text = 'Buy',  style = shape.labelup,   location = location.belowbar, color= color.green, textcolor = color.white, transp = 0, size = size.tiny)
        # pine_line:36 plotshape(sell, title = "Sell", text = 'Sell', style = shape.labeldown, location = location.abovebar, color= color.red,   textcolor = color.white, transp = 0, size = size.tiny)
        # pine_line:38 barcolor(barbuy  ? color.green : np.nan)
        # pine_line:39 barcolor(barsell ? color.red   : np.nan)
        # pine_line:41 alertcondition(buy,  "UT Long",  "UT Long")
        # pine_line:42 alertcondition(sell, "UT Short", "UT Short")
        return {
            'orders': self.orders,
            'positions': self.positions,
        }

# --- AlgoTrader: required entrypoint — connect your Pine logic to last-bar signal ---
def compute(closes, **params):
    if not closes:
        return {}
    # Return e.g. {"signal": "buy"} / {"signal": "sell"} or buy/sell booleans for the last bar.
    return {}
