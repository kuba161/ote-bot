# data/ — bring your own candles

Price data is **not** included: CME futures data exported from TradingView can't be redistributed.
Every `*.csv` in this folder is git-ignored.

## Expected files

| File | Used by |
|---|---|
| `mnq_15m.csv`, `mnq_1h.csv`, `mnq_4h.csv`, `mnq_1d.csv` | `backtest/run_backtest.py`, `validate_wf.py`, `validate_mc.py` |
| `archive/mnq_{15m,1h,4h,1d}_do_2026-06-11.csv` | `validate_forward.py` (the frozen in-sample period; its last bar is the parameter-freeze timestamp) |
| `raw/*.csv` | inputs for `merge_data.py` (edit `SOURCES` in that file to match your exports) |

`--instrument mes` reads `mes_*.csv` instead (see `INSTRUMENTS` in `backtest/config.py`).

## Format

```
time,open,high,low,close,volume
1772406000,24512.25,24530.5,24498.0,24521.75,1834
```

`time` is the bar **open** time in **UTC seconds**. The rows are ascending, with one file per timeframe.

## Getting the data

Any source works as long as it gives you the format above. I exported mine from TradingView.
TradingView only serves about 5,000 bars of 15m history (~2.5 months), so export at least every two
months. `merge_data.py` stitches the exports and stops if OHLC on the overlap doesn't match.
`engine.run_segmented` handles gaps longer than 4 days by running each continuous piece separately.
