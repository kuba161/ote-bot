# OTE Bot — backtest of an ICT "Fib OTE" strategy on Micro Nasdaq futures (MNQ)

I drew a discretionary trading idea on TradingView, turned it into my own Pine Script indicator, then
ported its logic **1:1 to Python** and tested it the honest way: freeze the parameters, then look at
data the strategy has never seen.

## The strategy
When market structure (break-of-structure bias) agrees on 1H, 4H and 1D, the bot places a limit order
at the **0.79 retracement** of the latest 15-minute Fibonacci leg. The entry also has to line up with a
Fair Value Gap, a weekly opening gap or a key session open, inside an ICT session. The stop goes beyond
the swing, the target at the nearest liquidity (prior day high/low), and position size comes from a
fixed $100 risk per trade.

## What's here

| File | What it does |
|---|---|
| `backtest/engine.py` | The backtest engine, plain Python (standard library only). It simulates 15m bars and reproduces TradingView's higher-timeframe semantics, so nothing looks into the future |
| `backtest/config.py` | All parameters, with comments |
| `backtest/run_backtest.py` | Runs the backtest on the whole window |
| `validate_forward.py` | The time-window test: in-sample vs forward on frozen parameters, plus a bootstrap confidence interval |

## How it was tested
1. **In-sample, 01.03–11.06.2026.** Every parameter was chosen on this period only, then frozen (27.06).
2. **Forward, 30.06–31.10.2026.** The frozen strategy runs on new data collected later. This is the
   part that counts.
3. Costs are included: 1 tick slippage on entry and stop, $0.74 commission per contract. When TP and SL
   are hit in the same 15m bar, the stop counts.

November 2026 is left out of the official window: it was an abnormal volatility regime (median daily
range 3.1% vs 1.3–2.5% in Jul–Oct). Its result is shown anyway in the last row.

## Results

| Period | Trades | PnL | Profit factor | Win rate | Avg per trade |
|---|---|---|---|---|---|
| In-sample (01.03–11.06) | 25 | **+$2,507** | 2.48 | 40% | +$100 |
| **Forward (30.06–31.10)** | **20** | **+$469** | **1.34** | 30% | **+$23** |
| Whole window (01.03–31.10) | 45 | +$2,976 | 1.97 | 36% | +$66 |
| Forward incl. November | 26 | −$540 | 0.77 | 23% | −$21 |

The strategy stayed profitable on data it had never seen, but the edge shrank by about 4× compared with
in-sample. The 95% confidence interval of the forward average per trade (bootstrap, 10,000 resamples)
is **−$58 to +$114**, which includes zero. So: a working engine and an honest test, but no proven edge
yet. The next step is more data.

## Running it
Python 3.9+, nothing to install.

```bash
python3 backtest/run_backtest.py     # whole-window backtest
python3 validate_forward.py          # in-sample vs forward + confidence interval
```

Both expect candles in `data/` (`mnq_15m.csv`, `mnq_1h.csv`, `mnq_4h.csv`, `mnq_1d.csv`, plus the frozen
in-sample copy in `data/archive/`). Format: `time,open,high,low,close,volume`, with `time` as the bar open
in UTC seconds. **The data isn't included:** it's CME market data exported from TradingView, and its
licence doesn't allow sharing.

Research project, not financial advice.
