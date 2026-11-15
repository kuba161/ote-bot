"""Test FORWARD: zamrozone parametry na danych, ktorych nikt nie widzial przy ich wyborze.

    ./venv/bin/python validate_forward.py          # raport + site/forward.json
    ./venv/bin/python validate_forward.py --no-json

Parametry zamrozono 27.06.2026 (R5) na danych do 11.06. Wszystko PO data/archive/*
(koniec starej proby) to czysty out-of-sample — w odroznieniu od validate_wf.py, ktory tnie te
same 102 dni. Okno forward zaczyna sie 30.06: 12.06-30.06 to dziura, ktorej TV juz nie oddaje
(15m siega ~5000 barow wstecz; patrz merge_data.py).

Co liczy:
  1. headline forward na defaultach z config.py (deny / provable / allow, miesiace, strony, filtry)
  2. IS vs forward: czy expectancy / PF / avg R utrzymuja znak
  3. retest hipotez zapisanych W R5, ZANIM te dane istnialy (4xTF, pivot 3-4, strefa OTE) —
     raportowane obok defaultu; defaultu NIE zmieniamy (decyzja Kuby: zakaz optymalizacji na OOS)
  4. kontrola rezimu: zwrot buy&hold MNQ w oknie (czy wynik to nie sam trend)
  5. werdykt wg kryterium Kuby: dodatni w OBU widelkach + stabilny miedzy miesiacami
"""
import argparse
import json
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backtest"))

import config
import engine
from engine import _et, _stats, load_csv, make_config, run_segmented
from merge_data import MNQU_FRONT
from validate_wf import _row

DATA = ROOT / "data"
SITE = ROOT / "site"
TFS = ("15m", "1h", "4h", "1d")
MIN_TRADES = 20       # ponizej: werdykt tylko orientacyjny

# hipotezy z R5 (WIEDZA.md §5/§8) — zapisane 27.06, przed tymi danymi
VARIANTS = [
    ("default", {}),
    ("4xTF", {"BIAS_TFS": ("15m", "1h", "4h", "1d")}),
    ("pivot3", {"PIVOT_LEN": 3}),
    ("pivot4", {"PIVOT_LEN": 4}),
    ("4xTF+pivot3", {"BIAS_TFS": ("15m", "1h", "4h", "1d"), "PIVOT_LEN": 3}),
    ("4xTF+pivot4", {"BIAS_TFS": ("15m", "1h", "4h", "1d"), "PIVOT_LEN": 4}),
    ("zone_705_79", {"ENTRY_FIBS": (0.705, 0.79)}),
    # R8 (15.11) — zarzadzanie pozycja; zarejestrowane przed liczeniem (diagnoza MFE przegranych)
    ("H1_partial1R", {"PARTIAL_R": 1.0, "PARTIAL_FRAC": 0.5}),
    ("H2_BE1R", {"BE_AT_R": 1.0}),
    ("H3_tpmax2.5", {"TP_MAX_R": 2.5}),
    ("H4_pivot4+BE1R", {"PIVOT_LEN": 4, "BE_AT_R": 1.0}),
    # R9 (15.11) — wejscie z potwierdzeniem zamiast slepego limitu; zarejestrowane przed liczeniem
    ("H5_confirm1", {"CONFIRM_ENTRY": True, "CONFIRM_BARS": 1}),
    ("H6_confirm3", {"CONFIRM_ENTRY": True, "CONFIRM_BARS": 3}),
    # R10 (15.11) — filtr zmiennosci; okno do 31.10, listopad = sprawdzian (--full)
    ("H7_vol90", {"VOL_FILTER": True, "VOL_PCTL": 90}),
    ("H7b_vol80", {"VOL_FILTER": True, "VOL_PCTL": 80}),
    ("H6+H7_vol90", {"CONFIRM_ENTRY": True, "CONFIRM_BARS": 3, "VOL_FILTER": True, "VOL_PCTL": 90}),
    ("H6+H7b_vol80", {"CONFIRM_ENTRY": True, "CONFIRM_BARS": 3, "VOL_FILTER": True, "VOL_PCTL": 80}),
]
MODES = ("deny", "provable", "allow")


def freeze_ts() -> int:
    """Ostatni bar 15m starej proby = granica IS / forward."""
    return load_csv(DATA / "archive" / "mnq_15m_do_2026-06-11.csv")[-1].ts


def split(trades, cut: int):
    closed = [t for t in trades if t.result]
    return [t for t in closed if t.entry_ts <= cut], [t for t in closed if t.entry_ts > cut]


def bucket(trades, keyfn) -> dict:
    out: dict = {}
    for t in trades:
        d = out.setdefault(keyfn(t), {"trades": 0, "wins": 0, "pnl": 0.0})
        d["trades"] += 1
        d["wins"] += t.pnl > 0
        d["pnl"] = round(d["pnl"] + t.pnl, 2)
    return dict(sorted(out.items()))


def bootstrap_ci(pnls: list[float], n_boot: int = 10000, seed: int = 42) -> dict:
    """95% przedzial ufnosci expectancy (srednia PnL na trade): losowanie trade'ow ze zwracaniem
    n_boot razy, percentyle 2.5 / 97.5 sredniej. Staly seed = powtarzalny wynik. n < 2 -> brak przedzialu."""
    n = len(pnls)
    mean = round(sum(pnls) / n, 2) if n else None
    if n < 2:
        return {"mean": mean, "lo": None, "hi": None, "n": n, "n_boot": n_boot}
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(pnls, k=n)) / n for _ in range(n_boot))
    return {"mean": mean, "lo": round(means[int(0.025 * n_boot)], 2),
            "hi": round(means[int(0.975 * n_boot) - 1], 2), "n": n, "n_boot": n_boot}


def buy_hold_pct(m15, lo: int, hi: int, skip_ts=(MNQU_FRONT[1],)) -> float:
    """Zwrot % trzymania MNQ w [lo, hi], z pominieciem skoku na rolce kontraktu (MNQ1! jest
    nieadjustowany: 14.09 cena przeskakuje o spread wrzesien->grudzien, to nie ruch rynku)."""
    bars = [b for b in m15 if lo <= b.ts <= hi]
    lr = sum(math.log(b.c / a.c) for a, b in zip(bars, bars[1:]) if b.ts not in skip_ts)
    return round(100 * (math.exp(lr) - 1), 2)


def verdict(st: dict, months: dict) -> tuple[str, str]:
    d, a = st["deny"], st["allow"]
    pos = sum(v["pnl"] > 0 for v in months.values())
    both = d["pnl_total"] > 0 and a["pnl_total"] > 0
    stable = pos * 2 >= len(months)
    why = (f"deny ${d['pnl_total']:.0f} / allow ${a['pnl_total']:.0f}, "
           f"miesiace dodatnie {pos}/{len(months)}, {st['provable']['trades']} tr")
    if not both:
        return "NO-GO", why
    if not stable:
        return "NO-GO (niestabilne)", why
    v = "GO*" if st["provable"]["trades"] >= MIN_TRADES else "GO* (orientacyjny)"
    return v, why


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-json", action="store_true", help="nie zapisuj site/forward.json")
    ap.add_argument("--full", action="store_true", help="wszystkie dane (ignoruj config.DATA_END)")
    args = ap.parse_args()

    data = tuple(load_csv(DATA / f"mnq_{tf}.csv") for tf in TFS)
    data = engine.clip_end(data, None if args.full else config.DATA_END)
    m15 = data[0]
    cut = freeze_ts()
    fwd_bars = [b for b in m15 if b.ts > cut]
    if not fwd_bars:
        raise SystemExit("Brak danych po starej probie — najpierw tvexport.mjs + merge_data.py")
    f0, f1 = fwd_bars[0].ts, fwd_bars[-1].ts
    print(f"IS:      {_et(m15[0].ts):%Y-%m-%d} -> {_et(cut):%Y-%m-%d} ET (parametry dobierane tutaj)")
    print(f"FORWARD: {_et(f0):%Y-%m-%d} -> {_et(f1):%Y-%m-%d} ET ({len(fwd_bars)} barow 15m, "
          f"dziura {_et(cut):%d.%m}-{_et(f0):%d.%m})")

    rows = []
    for name, ov in VARIANTS:
        row = {"name": name, "overrides": {k: list(v) if isinstance(v, tuple) else v for k, v in ov.items()},
               "is": {}, "fwd": {}}
        for mode in MODES:
            tr, *_ = run_segmented(make_config(config, {**ov, "ENTRY_BAR_TP": mode}), *data)
            is_tr, fw_tr = split(tr, cut)
            row["is"][mode], row["fwd"][mode] = _stats(is_tr), _stats(fw_tr)
            if mode == "provable":
                row["fwd_months"] = bucket(fw_tr, lambda t: _et(t.entry_ts).strftime("%Y-%m"))
                row["is_months"] = bucket(is_tr, lambda t: _et(t.entry_ts).strftime("%Y-%m"))
                if name == "default":
                    fw_default, is_default = fw_tr, is_tr
        row["verdict"], row["why"] = verdict(row["fwd"], row["fwd_months"])
        rows.append(row)

    d = rows[0]
    print("\n=== 1. FORWARD na zamrozonych defaultach ===")
    for mode in MODES:
        print(_row(f"forward {mode}", d["fwd"][mode]))
    print(f"  maxDD forward ${d['fwd']['provable']['max_drawdown']:.0f}")
    print("  miesiace:", {k: v["pnl"] for k, v in d["fwd_months"].items()})
    sides = bucket(fw_default, lambda t: t.side)
    filters = bucket(fw_default, lambda t: t.filter)
    kzs = bucket(fw_default, lambda t: t.kz)
    print("  strony:  ", {k: f"{v['trades']} tr ${v['pnl']:.0f}" for k, v in sides.items()})
    print("  filtry:  ", {k: f"{v['trades']} tr ${v['pnl']:.0f}" for k, v in filters.items()})
    print("  sesje:   ", {k: f"{v['trades']} tr ${v['pnl']:.0f}" for k, v in kzs.items()})

    print("\n=== 2. IS vs FORWARD (provable) ===")
    print(_row("IS (stara proba)", d["is"]["provable"]))
    print(_row("FORWARD", d["fwd"]["provable"]))
    ie, fe = d["is"]["provable"]["expectancy"], d["fwd"]["provable"]["expectancy"]
    ratio = round(fe / ie, 2) if ie else None
    print(f"  expectancy forward / IS = {ratio}  (avg R {d['is']['provable']['avg_r']} -> "
          f"{d['fwd']['provable']['avg_r']})")
    # 95% CI expectancy (bootstrap) — dla okna oficjalnego (config.DATA_END), chyba ze --full
    ci = {"is": bootstrap_ci([t.pnl for t in is_default]), "fwd": bootstrap_ci([t.pnl for t in fw_default])}
    for k, c in ci.items():
        if c["lo"] is not None:
            print(f"  expectancy {k.upper():<3} ${c['mean']:+.2f}/tr, 95% CI [${c['lo']:+.2f}, ${c['hi']:+.2f}] "
                  f"(bootstrap {c['n_boot']}x, {c['n']} tr)")

    print("\n=== 3. Hipotezy z R5 (zapisane przed tymi danymi) — default sie NIE zmienia ===")
    hdr = (f"  {'wariant':<13} | {'IS tr':>5} {'IS PnL':>7} {'PF':>5} | {'FWD tr':>6} {'deny':>7} "
           f"{'prov':>7} {'allow':>7} {'PF':>5} {'exp':>6} | mies+ | werdykt")
    print(hdr)
    for r in rows:
        i, f = r["is"]["provable"], r["fwd"]
        pf = lambda s: " inf" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
        pos = sum(v["pnl"] > 0 for v in r["fwd_months"].values())
        print(f"  {r['name']:<13} | {i['trades']:>5} {i['pnl_total']:>7.0f} {pf(i):>5} | "
              f"{f['provable']['trades']:>6} {f['deny']['pnl_total']:>7.0f} {f['provable']['pnl_total']:>7.0f} "
              f"{f['allow']['pnl_total']:>7.0f} {pf(f['provable']):>5} {f['provable']['expectancy']:>6.1f} | "
              f"{pos}/{len(r['fwd_months'])}   | {r['verdict']}")

    bh_is = buy_hold_pct(m15, m15[0].ts, cut)
    bh_fw = buy_hold_pct(m15, f0, f1)
    print("\n=== 4. Rezim rynku (buy&hold MNQ, bez skoku na rolce) ===")
    print(f"  IS {bh_is:+.1f}%   FORWARD {bh_fw:+.1f}%")
    print(f"  forward long {sides.get('long', {}).get('trades', 0)} tr / short "
          f"{sides.get('short', {}).get('trades', 0)} tr")

    print(f"\n=== 5. WERDYKT (default): {d['verdict']} — {d['why']} ===")
    print("  GO* = przewaga przezyla nowe dane; NIE oznacza 'handluj' — dalej to ~20 trade'ow.")

    if not args.no_json:
        out = {
            "is_period": [m15[0].ts, cut], "fwd_period": [f0, f1],
            "buy_hold_pct": {"is": bh_is, "fwd": bh_fw},
            "expectancy_ratio": ratio,
            "expectancy_ci95": ci,
            "default": {"sides": sides, "filters": filters, "killzones": kzs,
                        "trades": [vars(t) for t in fw_default]},
            "variants": rows,
            "min_trades": MIN_TRADES,
        }
        SITE.mkdir(exist_ok=True)
        (SITE / "forward.json").write_text(json.dumps(out, indent=1))
        print(f"\nZapisano {SITE / 'forward.json'}")


if __name__ == "__main__":
    main()
