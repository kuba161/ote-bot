"""Benchmark: strategia vs LOSOWE wejscia (stdlib only).

    python3 validate_random.py                 # 1000 przebiegow, okno oficjalne (config.DATA_END)
    python3 validate_random.py --runs 200      # szybciej
    python3 validate_random.py --full          # z listopadem

Pytanie: czy wybor MOMENTU i KIERUNKU wejscia (bias + noga Fib + 0.79 + filtr) cokolwiek daje, skoro
reszta (sesje, sizing, SL/TP, koszty) i tak by zarabiala albo tracila? Losowy trader dostaje dokladnie
te same zasady co strategia — tylko wejscie jest losowe:
- wejscie tylko na barach 15m w TRADE_SESSIONS, gdy noga Fib jest kompletna (po rozbiegu jak run_segmented),
- jedna pozycja naraz, kierunek 50/50, wejscie rynkowe na open bara,
- SL/TP z engine._exit_levels od nogi w tym kierunku (SL za swingiem, TP na plynnosci), gap-guard,
  sizing z _position_size (RISK_PER_TRADE_USD / MAX_RISK_USD), zarzadzanie i koszty z engine._manage.
Czestosc wejsc kalibrowana tak, zeby losowy trader mial srednio tyle trade'ow, co strategia.
Wynik: ktory percentyl rozkladu losowego osiaga strategia (expectancy i suma PnL), osobno cale okno
i czesc forward. Parametry strategii NIE sa zmieniane. -> site/random.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))

import config
import engine
from engine import (SEGMENT_WARMUP_BARS, Backtester, _et, _stats, killzone, load_csv,
                    make_config, run_segmented, split_segments)
from validate_forward import freeze_ts   # granica IS / forward (ostatni bar starej proby)

DATA = ROOT / "data"
SITE = ROOT / "site"
TFS = ("15m", "1h", "4h", "1d")
PILOT_RUNS = 30        # przebiegi kalibracji czestosci wejsc


def eligible_bars(bt: Backtester, cfg, warmup: int = 0) -> list[int]:
    """Bary, na ktorych losowy trader moze wejsc: sesja jak w strategii + kompletna noga Fib."""
    out = []
    sessions = getattr(cfg, "TRADE_SESSIONS", ())
    for i in range(max(1, warmup), len(bt.m15)):
        st = bt.legs[i - 1]
        if None in (st.sw_h, st.sw_l, st.run_min, st.run_max):
            continue
        if getattr(cfg, "SESSION_FILTER", False) and killzone(bt.m15[i].ts) not in sessions:
            continue
        out.append(i)
    return out


def random_run(bt: Backtester, elig: set[int], p: float, rng: random.Random) -> list:
    """Jeden przebieg losowego tradera na jednym ciaglym kawalku 15m."""
    trades: list = []
    pos = None
    for i in range(1, len(bt.m15)):
        b = bt.m15[i]
        if pos is not None and b.ts > pos.entry_ts:
            pos = bt._manage(pos, b, trades, idx=i)
        if pos is not None or i not in elig or rng.random() >= p:
            continue
        side = "long" if rng.random() < 0.5 else "short"
        st = bt.legs[i - 1]
        H, L = (st.sw_h, st.run_min) if side == "short" else (st.run_max, st.sw_l)
        if H <= L:
            continue
        fill = b.o
        sl, tp = bt._exit_levels(i, side, H, L, fill)
        # gap-guard jak w strategii + cel po stronie zysku (inaczej "TP" bylby natychmiastowa strata)
        if (fill >= sl or tp >= fill) if side == "short" else (fill <= sl or tp <= fill):
            continue
        contracts = bt._position_size(abs(fill - sl))
        if contracts is None:
            continue
        pos = bt._make_trade(side, b, fill, sl, tp, H, L, "random", contracts)
        pos = bt._manage(pos, b, trades, entry_bar=True, idx=i)
    return trades


def percentile_of(value: float, dist: list[float]) -> float:
    """Odsetek przebiegow losowych z wynikiem nizszym od value (remisy po polowie), 0-100."""
    if not dist:
        return float("nan")
    lo = sum(d < value for d in dist)
    eq = sum(d == value for d in dist)
    return round(100 * (lo + 0.5 * eq) / len(dist), 1)


def quantiles(dist: list[float]) -> dict:
    s = sorted(dist)
    q = lambda f: round(s[min(len(s) - 1, int(f * len(s)))], 2)
    return {"p5": q(0.05), "p50": q(0.50), "p95": q(0.95)}


def _metrics(trades: list) -> dict:
    st = _stats(trades)
    return {"trades": st["trades"], "pnl_total": st["pnl_total"], "expectancy": st["expectancy"],
            "profit_factor": st["profit_factor"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--full", action="store_true", help="wszystkie dane (ignoruj config.DATA_END)")
    ap.add_argument("--no-json", action="store_true", help="nie zapisuj site/random.json")
    args = ap.parse_args()

    data = tuple(load_csv(DATA / f"mnq_{tf}.csv") for tf in TFS)
    data = engine.clip_end(data, None if args.full else config.DATA_END)
    m15, h1, h4, d1 = data
    cfg = make_config(config)
    cut = freeze_ts()

    strat, *_ = run_segmented(cfg, *data)
    strat = [t for t in strat if t.result]

    # jeden Backtester na ciagly kawalek (prekomputacje raz), liczba trade'ow strategii per kawalek
    segs = []
    for k, seg in enumerate(split_segments(m15)):
        bt = Backtester(cfg, seg, h1, h4, d1)
        elig = eligible_bars(bt, cfg, SEGMENT_WARMUP_BARS if k else 0)
        n = sum(seg[0].ts <= t.entry_ts <= seg[-1].ts for t in strat)
        segs.append((bt, set(elig), n / len(elig) if elig else 0.0))

    def one_run(rng, scale):
        tr = []
        for bt, elig, p in segs:
            tr += random_run(bt, elig, min(1.0, p * scale), rng)
        return [t for t in tr if t.result]

    # kalibracja: pozycje blokuja kolejne wejscia, wiec surowe p daje mniej trade'ow niz strategia
    rng = random.Random(args.seed)
    pilot = sum(len(one_run(rng, 1.0)) for _ in range(PILOT_RUNS)) / PILOT_RUNS
    scale = len(strat) / pilot if pilot else 1.0

    rng = random.Random(args.seed + 1)
    runs = {"all": [], "fwd": []}
    for r in range(args.runs):
        tr = one_run(rng, scale)
        runs["all"].append(_metrics(tr))
        runs["fwd"].append(_metrics([t for t in tr if t.entry_ts > cut]))
        if (r + 1) % 200 == 0:
            print(f"  ... {r + 1}/{args.runs}", flush=True)

    s_all, s_fwd = _metrics(strat), _metrics([t for t in strat if t.entry_ts > cut])
    print(f"\nOkno: {_et(m15[0].ts):%Y-%m-%d} -> {_et(m15[-1].ts):%Y-%m-%d} ET, {args.runs} przebiegow, "
          f"seed {args.seed}, skala czestosci {scale:.2f}")
    out = {"runs": args.runs, "seed": args.seed, "freq_scale": round(scale, 3),
           "period": [m15[0].ts, m15[-1].ts], "fwd_from": cut, "parts": {}}
    for part, s in (("all", s_all), ("fwd", s_fwd)):
        dist = runs[part]
        res = {"strategy": s,
               "random_trades_mean": round(sum(d["trades"] for d in dist) / len(dist), 1)}
        for key in ("expectancy", "pnl_total"):
            vals = [d[key] for d in dist]
            res[key] = {"strategy": s[key], "percentile": percentile_of(s[key], vals), **quantiles(vals)}
        out["parts"][part] = res
        name = "CALE OKNO" if part == "all" else "FORWARD  "
        e, p = res["expectancy"], res["pnl_total"]
        print(f"  {name} strategia {s['trades']} tr, exp ${s['expectancy']:+.2f}/tr, PnL ${s['pnl_total']:+.0f} | "
              f"losowe srednio {res['random_trades_mean']} tr")
        print(f"            expectancy: percentyl {e['percentile']} (losowe p5 ${e['p5']:+.2f} / "
              f"p50 ${e['p50']:+.2f} / p95 ${e['p95']:+.2f})")
        print(f"            suma PnL:   percentyl {p['percentile']} (losowe p5 ${p['p5']:+.0f} / "
              f"p50 ${p['p50']:+.0f} / p95 ${p['p95']:+.0f})")
    print("  Percentyl >= 95 = strategia wyraznie lepsza od losowych wejsc; ~50 = nie do odroznienia.")

    if not args.no_json:
        SITE.mkdir(exist_ok=True)
        (SITE / "random.json").write_text(json.dumps(out, indent=1))
        print(f"\nZapisano {SITE / 'random.json'}")


if __name__ == "__main__":
    main()
