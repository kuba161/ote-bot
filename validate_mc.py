"""Monte Carlo / bootstrap walidacja przewagi na sekwencji trade'ow (stdlib only).

Odpowiada: czy PF/PnL bazowego backtestu to realna przewaga, czy szczescie na malej probce.
- BOOTSTRAP (resample z powtorzeniami): rozklad total PnL/expectancy, % serii dodatnich, percentyle.
- PERMUTACJA KOLEJNOSCI: rozklad max drawdown (kolejnosc trade'ow ma znaczenie dla DD).
- RYZYKO RUINY: % permutacji z drawdownem przekraczajacym zadany budzet konta.

Run: ./venv/bin/python validate_mc.py
"""
import argparse
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "backtest"))

import config
from engine import _stats, load_csv, make_config, run_segmented

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
N = 10000
SEED = 42


def max_drawdown(pnls: list[float]) -> float:
    eq = peak = mdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return mdd


def _pct(sorted_arr: list[float], p: float) -> float:
    return sorted_arr[int(p / 100 * (len(sorted_arr) - 1))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instrument", default="mnq", choices=list(config.INSTRUMENTS))
    args = ap.parse_args()
    inst = config.INSTRUMENTS[args.instrument]
    data = tuple(load_csv(DATA / f"{inst['prefix']}_{tf}.csv") for tf in ("15m", "1h", "4h", "1d"))
    cfg = make_config(config, {"TICK": inst["tick"], "POINT_VALUE": inst["point_value"]})
    trades, _funnel, _shadow, _bt = run_segmented(cfg, *data)
    pnls = [t.pnl for t in trades if t.result]
    n = len(pnls)
    if n == 0:
        print("Brak trade'ow w bazowym backteście.")
        return
    total = sum(pnls)
    s = _stats(trades)
    rng = random.Random(SEED)

    print(f"Bazowy backtest (default config): {n} trade'ow, PnL ${total:.0f}, "
          f"PF {s['profit_factor']}, expectancy ${total / n:.1f}/tr, WR {s['winrate']}%")

    # --- bootstrap: resample n trade'ow z powtorzeniami ---
    boot = []
    pos = 0
    for _ in range(N):
        tt = sum(pnls[rng.randrange(n)] for _ in range(n))
        boot.append(tt)
        pos += tt > 0
    boot.sort()
    print(f"\nBOOTSTRAP ({N}x resample {n} tr):")
    print(f"  total PnL:  p5 ${_pct(boot, 5):.0f}  |  p50 ${_pct(boot, 50):.0f}  |  p95 ${_pct(boot, 95):.0f}")
    print(f"  expectancy: p5 ${_pct(boot, 5) / n:.1f}/tr  |  p50 ${_pct(boot, 50) / n:.1f}/tr")
    print(f"  serie dodatnie: {100 * pos / N:.1f}%   (im blizej 100%, tym pewniejsza przewaga)")

    # --- permutacja kolejnosci: rozklad max drawdown ---
    dds = []
    for _ in range(N):
        perm = pnls[:]
        rng.shuffle(perm)
        dds.append(max_drawdown(perm))
    dds.sort()
    print(f"\nPERMUTACJA KOLEJNOSCI ({N}x) — max drawdown:")
    print(f"  p50 ${_pct(dds, 50):.0f}  |  p95 ${_pct(dds, 95):.0f}  |  p99 ${_pct(dds, 99):.0f}  |  worst ${dds[-1]:.0f}")

    # --- ryzyko ruiny: % permutacji z DD >= budzet konta ---
    print("\nRYZYKO RUINY (DD >= budzet konta, na permutacjach):")
    for acct in (1000, 2000, 3000, 5000):
        ruin = 100 * sum(d >= acct for d in dds) / N
        print(f"  konto ${acct}: {ruin:.1f}%")


if __name__ == "__main__":
    main()
