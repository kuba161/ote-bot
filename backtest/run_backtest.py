"""Uruchamia backtest strategii Fib OTE 0.79 na danych z data/ i zapisuje wyniki do site/.

Tryby:
  python run_backtest.py            # headline (provable) + widelki deny/allow + shadow
  python run_backtest.py --sweep    # dodatkowo siatka wariantow parametrow
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import engine
from engine import (_et, _stats, load_csv, make_config, run_segmented,
                    summarize, write_outputs)

_INSTR_OVR: dict = {}   # nadpisania instrumentu (TICK/POINT_VALUE), ustawiane w main()

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

RESOLUTIONS = ("deny", "provable", "allow")

# sweep: jeden czynnik na raz wzgledem baseline (= defaulty z config.py).
# Baseline 2026-06-26: BOS, BIAS_TFS=(1h,4h,1d), SESSION_FILTER=ON, EXIT_MODE=fib, displacement OFF.
# Baseline runda 4: BOS,(1h,4h,1d),sesja,EXIT=liquidity,SIZING=risk(cap400). Pytanie: OTE strefa vs pik 0.79.
SWEEP = [
    ("single_0.79", {}),
    ("zone_705_79", {"ENTRY_FIBS": (0.705, 0.79)}),
    ("zone_62_705_79", {"ENTRY_FIBS": (0.62, 0.705, 0.79)}),
    ("single_705", {"ENTRY_FIBS": (0.705,)}),
    ("single_62", {"ENTRY_FIBS": (0.62,)}),
    ("sizing_fixed", {"SIZING_MODE": "fixed"}),
]

ACCEPT_NOTE = ("Kryterium akceptacji: zmiana defaultow tylko gdy wynik dodatni/lepszy "
               "w OBU widelkach (deny i allow) i stabilny miedzy miesiacami — nie po "
               "maksymalnym PF pojedynczego wariantu na ~20 trade'ach.")


def run_variant(data, overrides):
    cfg = make_config(config, {**_INSTR_OVR, **overrides})
    trades, _funnel, _shadow, bt = run_segmented(cfg, *data)   # OTE-strefa + kawalki 15m po dziurach
    return bt, trades


def month_pnl(trades):
    out = {}
    for t in trades:
        if t.result:
            m = _et(t.entry_ts).strftime("%Y-%m")
            out[m] = round(out.get(m, 0.0) + t.pnl, 2)
    return out


def run_sweep(data):
    rows = []
    for name, ov in SWEEP:
        res, bm = {}, {}
        for mode in RESOLUTIONS:
            _, trades = run_variant(data, {**ov, "ENTRY_BAR_TP": mode})
            res[mode] = _stats(trades)
            if mode == "provable":
                bm = month_pnl(trades)
        rows.append({"name": name, "overrides": ov, "res": res, "by_month": bm})
    return {"rows": rows, "criterion": ACCEPT_NOTE}


def _pf(s):
    return "inf" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"


def print_sweep(sw):
    print("\n=== SWEEP (rozstrzygniecie intrabar: deny | provable | allow) ===")
    hdr = (f"{'wariant':<16} {'tr':>3} {'WR%':>5} | {'PnL deny':>9} {'PnL prov':>9} "
           f"{'PnL allow':>9} | {'PF d':>5} {'PF p':>5} {'PF a':>5} | {'mies+/-':>7}")
    print(hdr)
    print("-" * len(hdr))
    for row in sw["rows"]:
        d, p, a = (row["res"][m] for m in RESOLUTIONS)
        pos = sum(1 for v in row["by_month"].values() if v > 0)
        neg = sum(1 for v in row["by_month"].values() if v <= 0)
        print(f"{row['name']:<16} {p['trades']:>3} {p['winrate']:>5.1f} | "
              f"{d['pnl_total']:>9.2f} {p['pnl_total']:>9.2f} {a['pnl_total']:>9.2f} | "
              f"{_pf(d):>5} {_pf(p):>5} {_pf(a):>5} | {pos:>4}/{neg}")
    print("\n" + sw["criterion"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweep", action="store_true",
                    help="dodatkowo przelicz siatke wariantow parametrow")
    ap.add_argument("--instrument", default="mnq", choices=list(config.INSTRUMENTS),
                    help="instrument (dane data/{prefix}_*.csv + TICK/POINT_VALUE)")
    ap.add_argument("--full", action="store_true", help="wszystkie dane (ignoruj config.DATA_END)")
    args = ap.parse_args()

    inst = config.INSTRUMENTS[args.instrument]
    global _INSTR_OVR
    _INSTR_OVR = {"TICK": inst["tick"], "POINT_VALUE": inst["point_value"]}
    data = tuple(load_csv(DATA / f"{inst['prefix']}_{tf}.csv") for tf in ("15m", "1h", "4h", "1d"))
    data = engine.clip_end(data, None if args.full else config.DATA_END)
    m15 = data[0]
    print(f"Instrument: {args.instrument.upper()} (${inst['point_value']}/pkt)")
    print(f"Dane: 15m={len(m15)}  1H={len(data[1])}  4H={len(data[2])}  1D={len(data[3])}")
    print(f"Okno 15m: {_et(m15[0].ts):%Y-%m-%d %H:%M} -> {_et(m15[-1].ts):%Y-%m-%d %H:%M} ET")

    # headline: defaulty z config.py (ENTRY_BAR_TP="provable", GAP_GUARD on)
    bt, trades = run_variant(data, {})
    print(f"Struktura: FVG(>={config.FVG_MIN_PT}pt)={len(bt.fvgs)}  "
          f"NWOG={len(bt.nwogs)}  key opens={len(bt.key_opens)}")
    results = summarize(trades, m15, bt.cfg, bt.funnel)
    print("Lejek:", bt.funnel)

    # widelki rozstrzygniecia intrabar (prawda lezy miedzy deny a allow)
    for mode, key in (("deny", "variant_deny"), ("allow", "variant_allow")):
        _, tr = run_variant(data, {"ENTRY_BAR_TP": mode})
        results[key] = _stats(tr)

    # shadow: sygnaly odrzucone filtrem, symulowane identycznie (PnL per-sygnal, nie portfel)
    results["shadow_compare"] = {"real": results["stats"], "shadow": _stats(bt.shadow_trades)}
    results["shadow_trades"] = [vars(t) for t in bt.shadow_trades if t.result]

    if args.sweep:
        results["sweep"] = run_sweep(data)
        print_sweep(results["sweep"])

    SITE.mkdir(exist_ok=True)
    write_outputs(results, SITE / "results.json", SITE / "trades.csv")

    s = results["stats"]
    print("\n=== WYNIKI (headline = provable) ===")
    print(f"Trades: {s['trades']}  (W {s['wins']} / L {s['losses']}, winrate {s['winrate']}%)")
    print(f"PnL: ${s['pnl_total']}   PF: {s['profit_factor']}   expectancy: ${s['expectancy']}/trade")
    print(f"avg R: {s['avg_r']}   maxDD: ${s['max_drawdown']}")
    d, a = results["variant_deny"], results["variant_allow"]
    print(f"Widelki intrabar: deny ${d['pnl_total']} (PF {d['profit_factor']})  |  "
          f"allow ${a['pnl_total']} (PF {a['profit_factor']})")
    sh = results["shadow_compare"]["shadow"]
    print(f"Shadow (bez filtra, per-sygnal): {sh['trades']} sygnalow, PnL ${sh['pnl_total']}, "
          f"WR {sh['winrate']}%, PF {sh['profit_factor']}")
    print("\nFiltry:", {k: v["trades"] for k, v in results["by_filter"].items()})
    print("Strony:", {k: v["trades"] for k, v in results["by_side"].items()})
    print(f"\nZapisano: {SITE / 'results.json'} oraz {SITE / 'trades.csv'}")


if __name__ == "__main__":
    main()
