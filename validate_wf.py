"""Walk-forward / anchored out-of-sample walidacja + analiza plateau parametrow (stdlib only).

Odpowiada na pytanie, ktorego MC (validate_mc.py) NIE odpowiada: czy +$2507 to realna
przewaga, czy dopasowanie do jednego okna i do pikow parametrow. MC resampluje TE SAME
trade'y (rozklad in-sample); tu parametry wybierane sa WYLACZNIE na train i oceniane na
osobnym oknie test (OOS) — to test falsyfikujacy.

  ANCHORED SPLIT  : train = pierwsze --frac danych 15m, test = reszta. Silnik na train widzi
                    dane tylko do granicy; na test ma pelny lookback (jak live), ale liczymy
                    wylacznie wejscia po granicy. Degradacja expectancy IS->OOS.
  PLATEAU         : skan kluczowych parametrow NA TRAIN — czy default siedzi na ostrym piku
                    czy na szerokim plateau; robustny srodek + fragility (+-1 krok).
  TRAIN->TEST     : czy wartosc najlepsza na train trzyma sie na test (proxy overfittingu wyboru).
  WERDYKT         : GO / NO-GO przed inwestycja w dane (#1) lub bota (#3).

Run: ./venv/bin/python validate_wf.py [--instrument mnq] [--frac 0.6] [--no-json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "backtest"))

import config
from engine import _et, _stats, load_csv, make_config, run_segmented

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE = ROOT / "site"

# --- siatki parametrow ---
# ordered: maja sens "plateau" (uporzadkowane); ovfn(v) -> nadpisania configu, default = wartosc bazowa
ORDERED = [
    ("ENTRY_FIB", lambda v: {"ENTRY_FIB": v, "ENTRY_FIBS": (v,)},
     [0.70, 0.72, 0.75, 0.77, 0.79, 0.81, 0.83, 0.85], 0.79),
    ("PIVOT_LEN", lambda v: {"PIVOT_LEN": v, "STRUCT_PIVOT_LEN": v},
     [3, 4, 5, 6, 7], 5),
    ("SL_BUFFER_TICKS", lambda v: {"SL_BUFFER_TICKS": v}, [2, 4, 6, 8], 4),
    ("TP_MIN_R", lambda v: {"TP_MIN_R": v}, [0.5, 1.0, 1.5, 2.0], 1.0),
    ("TP_MAX_R", lambda v: {"TP_MAX_R": v}, [3.0, 4.0, 5.0, 6.0], 4.0),
]
# categorical: bez plateau, tylko porownanie train vs test
CATEGORICAL = [
    ("BIAS_TFS", lambda v: {"BIAS_TFS": v},
     [("1h", "4h", "1d"), ("15m", "1h", "4h", "1d"), ("4h", "1d"), ("1h", "4h")],
     ("1h", "4h", "1d")),
    ("EXIT_MODE", lambda v: {"EXIT_MODE": v}, ["liquidity", "fib"], "liquidity"),
    ("BIAS_METHOD", lambda v: {"BIAS_METHOD": v}, ["BOS", "HH/HL", "EMA20"], "BOS"),
]


# --- okna danych ---
def split_ts(m15, frac: float) -> int:
    """Granica czasowa = ts bara na pozycji frac*len (po liczbie barow, nie kalendarzu)."""
    return m15[max(1, min(len(m15) - 1, int(frac * len(m15))))].ts


def run_to(cfg, data, build_to_ts: int):
    """Uruchom silnik na danych 15m do build_to_ts (HTF pelne = lookback). Domkniete trade'y."""
    m15, h1, h4, d1 = data
    m15s = [b for b in m15 if b.ts <= build_to_ts]
    trades, *_ = run_segmented(cfg, m15s, h1, h4, d1)
    return [t for t in trades if t.result]


def in_window(trades, lo: int, hi: int):
    """Trade'y z wejsciem w [lo, hi)."""
    return [t for t in trades if lo <= t.entry_ts < hi]


def split_stats(cfg, data, t0: int, sp: int, t1: int):
    """(train_stats, test_stats, train, test). Podzial po entry_ts: train = wejscia [t0, sp),
    test = [sp, t1]. Parametry zamrozone na calym oknie; pozycja otwarta tuz przed granica
    domyka sie normalnie (realistyczne, NIE leak wyboru parametrow — wybor patrzy tylko na
    train, entry<sp). Sanity: PnL(train)+PnL(test) = PnL(pelny backtest)."""
    full = run_to(cfg, data, t1)
    train, test = in_window(full, t0, sp), in_window(full, sp, t1 + 1)
    return _stats(train), _stats(test), train, test


# --- skan + plateau ---
def scan(cfg, data, t0, sp, t1, ovfn, values):
    rows = []
    for v in values:
        c = make_config(cfg, ovfn(v))
        st_tr, st_te, _, _ = split_stats(c, data, t0, sp, t1)
        rows.append({"val": v, "train": st_tr, "test": st_te})
    return rows


def plateau_idx(rows, metric="pnl_total") -> int:
    """Indeks robustnego srodka plateau: maks. MIN metryki w oknie +-1 (penalizuje
    sasiedztwo przepasci). Tylko wnetrze (sasiad z obu stron) — brzeg nie jest srodkiem."""
    n = len(rows)
    if n < 3:
        return argmax_idx(rows, metric)
    vals = [(r["train"][metric] or 0.0) for r in rows]
    best_i, best = 1, float("-inf")
    for i in range(1, n - 1):
        s = min(vals[i - 1], vals[i], vals[i + 1])
        if s > best:
            best, best_i = s, i
    return best_i


def argmax_idx(rows, metric="pnl_total") -> int:
    return max(range(len(rows)), key=lambda i: rows[i]["train"][metric] or 0.0)


def default_idx(values, default) -> int:
    return values.index(default) if default in values else -1


# --- formatowanie ---
def _pf(s) -> str:
    return " inf" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"


def _row(label, s) -> str:
    return (f"  {label:<22} {s['trades']:>3} tr  PnL ${s['pnl_total']:>8.0f}  "
            f"PF {_pf(s):>5}  WR {s['winrate']:>4.0f}%  exp ${s['expectancy']:>6.1f}/tr")


def fmt_val(v) -> str:
    if isinstance(v, tuple):
        return "+".join(str(x) for x in v)
    return str(v)


# --- raport ---
def report(cfg, data, frac: float):
    m15 = data[0]
    t0, t1 = m15[0].ts, m15[-1].ts
    sp = split_ts(m15, frac)
    out = {"frac": frac, "split_ts": sp,
           "split_date": f"{_et(sp):%Y-%m-%d %H:%M}",
           "from": f"{_et(t0):%Y-%m-%d}", "to": f"{_et(t1):%Y-%m-%d}"}

    print(f"Okno 15m: {_et(t0):%Y-%m-%d} -> {_et(t1):%Y-%m-%d} ET  ({len(m15)} barow)")
    print(f"Anchored split {frac:.0%}/{1 - frac:.0%}  granica = {_et(sp):%Y-%m-%d %H:%M} ET")

    # 1) DEFAULTY: IS vs OOS (sanity vs reczny IS/OOS z CLAUDE.md)
    st_tr, st_te, _, _ = split_stats(cfg, data, t0, sp, t1)
    out["default"] = {"train": st_tr, "test": st_te}
    print("\n=== DEFAULTY: in-sample (train) vs out-of-sample (test) ===")
    print(_row("TRAIN (optymalizacja)", st_tr))
    print(_row("TEST  (OOS, nietkniety)", st_te))
    deg = degradation(st_tr, st_te)
    out["default"]["degradation_exp"] = deg
    print(f"  degradacja expectancy OOS/IS: {deg}   "
          f"znak OOS: {'+' if st_te['pnl_total'] > 0 else '-'}  "
          f"PF OOS: {_pf(st_te)}")

    # 2) PLATEAU: skan parametrow na TRAIN, walidacja wyboru na TEST
    print("\n=== PLATEAU PARAMETROW (skan na TRAIN; czy default to pik czy plaskowyz) ===")
    print("  (znaczniki: D=default, *=argmax train, ==srodek plateau)")
    scans, overfit_flags = [], []
    for label, ovfn, values, dflt in ORDERED:
        rows = scan(cfg, data, t0, sp, t1, ovfn, values)
        di = default_idx(values, dflt)
        ai = argmax_idx(rows)
        pi = plateau_idx(rows)
        # fragility defaultu: spadek vs srednia sasiadow (train)
        frag = fragility(rows, di) if di >= 0 else None
        # overfit wyboru: najlepsza-na-train wartosc — jej rank na test
        flag = train_pick_holds(rows, ai)
        overfit_flags.append(flag)
        scans.append({"param": label, "values": [fmt_val(v) for v in values],
                      "rows": rows, "default_i": di, "argmax_i": ai, "plateau_i": pi,
                      "fragility": frag, "pick_holds": flag})
        print(f"\n  [{label}]  (def={fmt_val(values[di]) if di >= 0 else '?'}, "
              f"argmax_train={fmt_val(values[ai])}, plateau={fmt_val(values[pi])})")
        print(f"  {'wartosc':<10} | {'PnL tr':>8} {'PF tr':>6} {'tr':>3} | "
              f"{'PnL te':>8} {'PF te':>6} {'tr':>3}")
        for j, r in enumerate(rows):
            mark = "".join(["D" if j == di else " ", "*" if j == ai else " ",
                            "=" if j == pi else " "])
            print(f"  {fmt_val(r['val']):<10}{mark}| "
                  f"{r['train']['pnl_total']:>8.0f} {_pf(r['train']):>6} {r['train']['trades']:>3} | "
                  f"{r['test']['pnl_total']:>8.0f} {_pf(r['test']):>6} {r['test']['trades']:>3}")
        if frag is not None:
            print(f"  fragility defaultu (+ = pik/kruche, - = stabilne): {frag:+.0%}")
        print(f"  najlepsza-na-train ({fmt_val(values[ai])}) na TEST: "
              f"{'TRZYMA (>= mediana OOS)' if flag else 'NIE TRZYMA (< mediana OOS)'}")
    out["scans"] = [_scan_json(s, values_for(s["param"])) for s in scans]

    # 3) CATEGORICAL: warianty bez plateau
    print("\n=== WARIANTY KATEGORYCZNE (train vs test) ===")
    cat = []
    for label, ovfn, values, dflt in CATEGORICAL:
        rows = scan(cfg, data, t0, sp, t1, ovfn, values)
        cat.append({"param": label, "rows": rows, "default": fmt_val(dflt)})
        print(f"\n  [{label}]  (def={fmt_val(dflt)})")
        for r in rows:
            d = " <- def" if r["val"] == dflt else ""
            print(f"  {fmt_val(r['val']):<18} | train PnL ${r['train']['pnl_total']:>7.0f} "
                  f"PF {_pf(r['train']):>5} | test PnL ${r['test']['pnl_total']:>7.0f} "
                  f"PF {_pf(r['test']):>5}{d}")
    out["categorical"] = [_cat_json(c) for c in cat]

    # 4) PROXY OVERFITTINGU WYBORU
    held = sum(1 for f in overfit_flags if f)
    pbo = 1 - held / len(overfit_flags) if overfit_flags else 0.0
    out["overfit_proxy"] = round(pbo, 2)
    print(f"\n=== PROXY OVERFITTINGU WYBORU ===")
    print(f"  W {held}/{len(overfit_flags)} parametrach najlepsza-na-train trzyma sie >= mediana OOS.")
    print(f"  Proxy overfittingu (im wyzej, tym gorzej): {pbo:.0%}")

    # 5) WERDYKT
    verdict, reasons = decide(st_te, overfit_flags, scans)
    out["verdict"] = verdict
    out["reasons"] = reasons
    print(f"\n{'=' * 60}\n  WERDYKT: {verdict}\n{'=' * 60}")
    for r in reasons:
        print(f"  - {r}")
    print(f"\n  UWAGA: OOS = {st_te['trades']} trade'ow. To brama go/no-go (ujawnia kruchosc),")
    print(f"  NIE dowod przewagi. Dowod = wieksza probka (#1 dane) lub forward-test (#3 Tradovate).")
    return out


# --- metryki pomocnicze ---
def degradation(tr, te) -> str:
    a, b = tr["expectancy"], te["expectancy"]
    if a == 0:
        return "n/d"
    flip = "  ZNAK ODWROCONY" if (a > 0) != (b > 0) else ""
    return f"{b / a:+.0%} (${a:.0f}->${b:.0f}/tr){flip}"


def fragility(rows, di) -> float | None:
    """Kruchosc defaultu: o ile spadnie PnL_train przy ruszeniu o +-1 krok.
    + = default to lokalny pik (kruche), - = sasiedzi lepsi (stabilne)."""
    base = rows[di]["train"]["pnl_total"]
    nb = [rows[i]["train"]["pnl_total"] for i in (di - 1, di + 1) if 0 <= i < len(rows)]
    if not nb or base == 0:
        return None
    return (base - sum(nb) / len(nb)) / abs(base)


def train_pick_holds(rows, ai) -> bool:
    """Czy wartosc najlepsza na train ma na TEST wynik >= mediana wynikow test."""
    te = sorted(r["test"]["pnl_total"] for r in rows)
    med = te[len(te) // 2] if len(te) % 2 else (te[len(te) // 2 - 1] + te[len(te) // 2]) / 2
    return rows[ai]["test"]["pnl_total"] >= med


def decide(st_te, flags, scans):
    reasons = []
    oos_ok = st_te["pnl_total"] > 0 and (st_te["profit_factor"] is None or st_te["profit_factor"] > 1)
    reasons.append(("OOS dodatni (PnL>0, PF>1)" if oos_ok else "OOS NIE dodatni") +
                   f": ${st_te['pnl_total']:.0f}, PF {_pf(st_te)}")
    held = sum(1 for f in flags if f)
    pick_ok = held >= len(flags) / 2
    reasons.append(f"Wybor train->test trzyma sie w {held}/{len(flags)} parametrach"
                   + (" (OK)" if pick_ok else " (slabo)"))
    # czy default kazdego ordered jest blisko plateau (|default_i - plateau_i| <= 1)
    near = sum(1 for s in scans if s["default_i"] >= 0 and abs(s["default_i"] - s["plateau_i"]) <= 1)
    plateau_ok = near >= len(scans) / 2
    reasons.append(f"Default na/przy plateau w {near}/{len(scans)} parametrach"
                   + (" (OK)" if plateau_ok else " (siedzi na klifach)"))
    go = oos_ok and pick_ok and plateau_ok
    return ("GO (przejdz do forward-test #3 / wiecej danych #1)" if go
            else "NO-GO (przewaga prawdopodobnie dopasowana — najpierw #1 dane)"), reasons


# --- JSON helpers ---
def values_for(param):
    for label, _, values, _ in ORDERED:
        if label == param:
            return values
    return []


def _scan_json(s, values):
    return {"param": s["param"], "values": s["values"],
            "train_pnl": [r["train"]["pnl_total"] for r in s["rows"]],
            "test_pnl": [r["test"]["pnl_total"] for r in s["rows"]],
            "train_pf": [r["train"]["profit_factor"] for r in s["rows"]],
            "test_pf": [r["test"]["profit_factor"] for r in s["rows"]],
            "default_i": s["default_i"], "argmax_i": s["argmax_i"],
            "plateau_i": s["plateau_i"], "fragility": s["fragility"],
            "pick_holds": s["pick_holds"]}


def _cat_json(c):
    return {"param": c["param"], "default": c["default"],
            "rows": [{"val": fmt_val(r["val"]), "train": r["train"], "test": r["test"]}
                     for r in c["rows"]]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instrument", default="mnq", choices=list(config.INSTRUMENTS))
    ap.add_argument("--frac", type=float, default=0.6, help="udzial train (anchored split)")
    ap.add_argument("--no-json", action="store_true", help="nie zapisuj site/wf.json")
    args = ap.parse_args()

    inst = config.INSTRUMENTS[args.instrument]
    data = tuple(load_csv(DATA / f"{inst['prefix']}_{tf}.csv") for tf in ("15m", "1h", "4h", "1d"))
    cfg = make_config(config, {"TICK": inst["tick"], "POINT_VALUE": inst["point_value"]})
    print(f"Instrument: {args.instrument.upper()} (${inst['point_value']}/pkt)\n")

    out = report(cfg, data, args.frac)
    out["instrument"] = args.instrument

    if not args.no_json:
        SITE.mkdir(exist_ok=True)
        with open(SITE / "wf.json", "w") as f:
            json.dump(out, f, indent=1)
        print(f"\nZapisano: {SITE / 'wf.json'}")


if __name__ == "__main__":
    main()
