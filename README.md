# OTE Bot — backtesting an ICT "Fib OTE" strategy on Micro Nasdaq futures

[![tests](https://github.com/kuba161/ote-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/kuba161/ote-bot/actions/workflows/tests.yml)

**Live dashboard:** https://kuba161.github.io/ote-bot/ (equity curve, every trade, forward-test card; labels in Polish)

A research project that takes a discretionary trading idea I drew by hand on TradingView, turns it
into a Pine Script indicator, ports the logic **1:1 to Python**, and then tries hard to prove it
**doesn't** work. It's a test of how I do the research, not a signal service.

> **Result first:** the strategy looked great in-sample (+$2,507, PF 2.48 on 25 trades). On data
> collected *after* every parameter was frozen (30.06–31.10.2026) it stayed positive but thin:
> **+$469, PF 1.34, 20 trades**, with almost all of that from one trade. Walk-forward out-of-sample is
> close to zero (+$74, PF 1.07). In short: no proven edge yet. The interesting part is *how* that
> became visible, so that's what this repo documents.
>
> The official analysis window ends on **31 October 2026**. November 2026 was an abnormal volatility
> regime (median daily range 3.1% vs 1.3–2.5% in Jul–Oct). Including it, the forward test is
> **−$540, PF 0.77, 26 trades**. I picked the window *after* seeing November, so a volatility rule set
> in advance was tested on November too (round 10 below).

## The strategy (in two sentences)
When market structure (break-of-structure bias) agrees on 1H, 4H and 1D, place a limit order at the
**0.79 retracement** ("optimal trade entry") of the latest 15-minute Fibonacci leg. The entry also
has to line up with a 15m Fair Value Gap, a New Week Opening Gap or a key session open (00:00 /
10:00 / 18:00 New York time), and it has to come during an ICT session. Exits go to the nearest
liquidity (prior day high/low, opposite end of the leg), with risk-based position sizing.

## What's in here

| Path | What it is |
|---|---|
| `pine/ict_setup_nq_all_in_one.pine` | The TradingView indicator (Pine v6) the logic was born in: rejection blocks, FVG/IFVG state machine, MTF FVG, session opens/highs/lows, structure bias dashboard, Fib 15m OTE row, SMT divergence, alerts |
| `backtest/engine.py` | Event-driven backtest engine, **Python stdlib only**. It reproduces the indicator's `request.security(..., lookahead_on)[1]` semantics so the higher-timeframe values don't repaint |
| `backtest/config.py` | Every knob, with comments. Ideas the data rejected stay in as toggles, switched OFF |
| `backtest/run_backtest.py` | Headline backtest + `--sweep` grid |
| `validate_mc.py` | Monte Carlo: bootstrap of trades, drawdown permutations, risk of ruin |
| `validate_wf.py` | Anchored walk-forward: parameters picked **only** on train, scored on a disjoint test set |
| `validate_forward.py` | True forward test on data collected *after* the parameters were frozen |
| `merge_data.py` | Stitches TradingView exports and **refuses** to merge if OHLC on the overlap disagrees (catches mixing different contracts) |
| `backtest/test_*.py` | 66 unit/e2e tests on synthetic bars (fills, gaps, intrabar rules, sizing, exits, entry confirmation) |
| `site/` | Static dashboard (vanilla JS) with the latest results: equity curve, trade list, forward-test card |

## Methodology — ten rounds

1. **Engine rebuild.** Intrabar ambiguity is shown as a *deny/allow bracket* (worst/best case for
   bars where both TP and SL were touched), not hidden. It adds a gap guard, MAE/MFE and "shadow
   trades" for every signal a filter rejected.
2. **Bias: EMA20 → market structure (BOS).** −$253 → +$554 on the same data.
3. **Sessions + liquidity exits.** These made the deny/allow bracket collapse into one number.
4. **Risk-based sizing.** Constant $ risk per trade instead of a constant contract count (risk per
   trade used to swing 16×).
5. **Robustness.** Sensitivity scans showed the defaults sat on peaks, which is the first warning sign.
6. **Walk-forward (out-of-sample).** **NO-GO**: the edge was concentrated in March–April. Monte Carlo
   had said "95% of runs profitable", but it was circular, because it resampled the same 25 trades.
7. **Forward test on frozen parameters**, data collected *after* the freeze (30.06–13.11.2026):

| | trades | PnL | PF | win rate | expectancy |
|---|---|---|---|---|---|
| In-sample (01.03–11.06) | 25 | +$2,507 | 2.48 | 40% | $100 / trade |
| **Forward, official window (to 31.10)** | **20** | **+$469** | **1.34** | 30% | **$23 / trade** |
| Forward incl. November (to 13.11) | 26 | −$540 | 0.77 | 23% | −$21 / trade |

Every hypothesis variant written down *before* the forward data arrived (4-TF bias, pivot 3/4,
scale-in zone) is also negative on the forward test.

8. **Trying to fix the exits (R8).** The trade log said 14 of 20 forward losers had been +1R in profit
   before stopping out, so partial profit at 1R, break-even at 1R and a closer target looked like
   obvious fixes. They weren't. **The diagnosis was a measurement artefact.** For limit fills in the
   middle of a bar, the engine counted that bar's whole high/low as favourable excursion, including
   the move *before* the fill. With that fixed, only 6 of 20 losers had ever been +1R. The losers go
   straight to the stop, so the problem is the entries. No variant passed the acceptance criterion.
   Pivot 4 + break-even at 1R was the only one positive on forward in both brackets (+$131 / +$580),
   but with only 1 of 5 positive months it fails the stability bar, and the default stays.

9. **Fixing the entries (R9).** With the losers going straight to the stop, the obvious fix was to stop
   using a blind limit order. Instead the bot waits until a 15m candle closes back beyond the OTE level
   (a rejection) and enters at the next open. With a 3-bar confirmation window, 23 setups that would have
   hit the stop before confirming were filtered out. The forward test turned positive: **+$363, PF 1.42**,
   and the deny/allow bracket collapsed to one number, because a market entry on the open leaves no
   intrabar ambiguity. But in-sample profit dropped from $2,507 to $1,316, and it rests on only 11
   forward trades. It fails the "better on *both* periods" criterion, so it's a candidate for the next
   round of fresh data, not a new default.

10. **Analysis window and a volatility filter (R10).** I ended the official window on 31.10, because
    November was an abnormal regime. Since that choice was made *after* seeing November, I also tested a
    rule fixed in advance: no new entries when the previous day's range is above the 90th (or 80th)
    percentile of the prior 252 days. It flags 5 of 10 November sessions and roughly halves the November
    losses. But no variant beats the default on *both* periods, so the default stays.

### Lessons I'd keep
- **Monte Carlo on your own backtest trades is not validation.** It only tells you about the
  in-sample distribution.
- **What optimisation rejected in-sample sometimes generalised better.** That's the classic
  overfitting signature.
- **Freeze parameters, then wait for new data.** It's the only test you can't fool yourself on.
- **Check your metrics before you trust a diagnosis.** One wrong excursion measure would have sent me
  optimising the wrong half of the strategy.
- **Write down rejected ideas with their numbers** and the reason, so
  you don't re-test them six weeks later.

## Running it

Python 3.9+ and nothing else (stdlib only). `pytest` is only needed for the tests.

```bash
# dashboard with the committed results
python3 -m http.server 8420 --directory site    # → http://localhost:8420

# tests (data-dependent ones are skipped without data/)
python3 -m pip install pytest && python3 -m pytest backtest/
```

To re-run the backtest you need your own candles in `data/`. See [`data/README.md`](data/README.md):

```bash
python3 backtest/run_backtest.py          # headline + writes site/results.json
python3 validate_wf.py                    # walk-forward
python3 validate_mc.py                    # Monte Carlo
python3 validate_forward.py               # forward test  → site/forward.json
# all scripts use config.DATA_END (31.10.2026); add --full to include November
```

## Why there is no price data
The candles are CME market data exported from TradingView. Their licence doesn't allow
redistribution, so `data/*.csv` is git-ignored. The results in `site/` are derived from that data
and are included.

## Disclaimer
Research and education only. **Not financial advice.** The strategy failed out-of-sample, so please
don't trade it.

## License
MIT. See [`LICENSE`](LICENSE).
