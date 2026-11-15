"""
Backtest: Midnight Open (00:00 ET) retest o ~8:30 NY — strategia reversal / "fade".

Pytanie Kuby:
  1) ile razy w ~3 mies. cena dotknęła linii midnight open (00:00 ET) w oknie ~8:30 NY,
  2) czy fade tego poziomu o 8:30 (RR 4:1, SL 10 pkt MNQ) jest profitable.

Reużywa z engine.py: load_csv, _et, compute_key_opens, Bar; z config.py: TICK/POINT_VALUE/slippage.
Dane: data/mnq_15m.csv (mar–cze 2026, 74 dni z barem 00:00 ET).

OGRANICZENIA (świadome, wybrane przez Kubę):
  - Najdrobniejsze świece = 15m → "±5min od 8:30" zgrubione do świecy 08:30–08:45 ET.
  - Okres mar–cze (nie ostatnie 3 mies — tyle 15m historii daje TV).
  - Kolejność SL/TP wewnątrz świecy 15m nieznana → raport widełek deny(SL first)/allow(TP first)
    + "provable" (trade'y, w których wynik jest jednoznaczny niezależnie od kolejności).

Uruchom:  cd ote_bot && ./venv/bin/python3 backtest/midnight_open_830.py
"""
from __future__ import annotations
import os
import sys
import json
from datetime import timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import load_csv, _et, compute_key_opens, Bar  # noqa: E402
import config as C  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "mnq_15m.csv")

SL_PT = 10.0          # stop loss w punktach
RR = 4.0
TP_PT = SL_PT * RR    # 40 pkt (RR 4:1)

SLIP_ENTRY = C.SLIPPAGE_TICKS_ENTRY * C.TICK   # adverse na wejściu (pkt)
SLIP_STOP = C.SLIPPAGE_TICKS_STOP * C.TICK     # adverse na SL (pkt)
PV = C.POINT_VALUE                             # $/pkt (MNQ = 2.0)


def sess_key(ts: int):
    """Dzień sesyjny CME — 'D' zaczyna się 18:00 ET (jak _new_session_day w engine)."""
    return (_et(ts) - timedelta(hours=18)).date()


def simulate(side: str, sl: float, tp: float, bars: list[Bar], i0: int, ambig_pref: str):
    """Przejdź świece od wejścia (i0) do SL/TP; limit = koniec dnia sesyjnego (mark-to-market na close).
    ambig_pref: 'sl' (deny) albo 'tp' (allow) — rozstrzyga świecę, która dotknęła SL i TP naraz.
    Zwraca (kind, exit_price, ambiguous_bool)."""
    dkey = sess_key(bars[i0].ts)
    ambiguous = False
    for j in range(i0, len(bars)):
        b = bars[j]
        if sess_key(b.ts) != dkey:                     # nowy dzień sesyjny → koniec okna
            return "mtm", bars[j - 1].c, ambiguous
        if side == "long":
            hit_sl, hit_tp = b.l <= sl, b.h >= tp
        else:
            hit_sl, hit_tp = b.h >= sl, b.l <= tp
        if hit_sl and hit_tp:
            ambiguous = True
            return ("sl", sl, ambiguous) if ambig_pref == "sl" else ("tp", tp, ambiguous)
        if hit_sl:
            return "sl", sl, ambiguous
        if hit_tp:
            return "tp", tp, ambiguous
    return "mtm", bars[-1].c, ambiguous            # koniec danych


def pnl_pt(side: str, entry: float, kind: str, exit_price: float, sl: float, tp: float) -> float:
    d = 1.0 if side == "long" else -1.0
    entry_eff = entry + d * SLIP_ENTRY             # adverse: long wchodzi wyżej, short niżej
    if kind == "sl":
        ex = sl - d * SLIP_STOP                     # adverse poślizg na stopie
    elif kind == "tp":
        ex = tp                                     # limit — bez poślizgu
    else:
        ex = exit_price                             # mark-to-market na close
    return (ex - entry_eff) * d


def agg(trades: list[dict], key: str):
    """Statystyki dla wybranego wariantu wyniku ('deny'/'allow')."""
    pnl = [t[key] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    gross_w = sum(wins)
    gross_l = -sum(losses)
    total = sum(pnl)
    # max drawdown na krzywej kapitału
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for p in pnl:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    n = len(pnl)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": (len(wins) / n * 100) if n else 0.0,
        "pnl_pt": total,
        "pnl_usd": total * PV,
        "pf": (gross_w / gross_l) if gross_l > 0 else float("inf"),
        "exp_pt": (total / n) if n else 0.0,
        "exp_usd": (total / n * PV) if n else 0.0,
        "exp_R": (total / SL_PT / n) if n else 0.0,
        "maxdd_usd": maxdd * PV,
    }


def main():
    bars = load_csv(os.path.abspath(DATA))

    # grupuj świece po dniu sesyjnym → {hhmm: (idx, Bar)}
    days: dict = defaultdict(dict)
    order: list = []
    for i, b in enumerate(bars):
        d = sess_key(b.ts)
        if d not in days:
            order.append(d)
        hhmm = _et(b.ts).strftime("%H:%M")
        days[d].setdefault(hhmm, (i, b))

    n_days_mo = sum(1 for d in order if "00:00" in days[d])
    trades: list[dict] = []
    n_touch = n_notouch = n_skip_eq = n_nopair = 0

    for d in order:
        day = days[d]
        if "00:00" not in day or "08:30" not in day:
            n_nopair += 1
            continue
        mo = day["00:00"][1].o                         # midnight open (open świecy 00:00 ET)
        i0, b = day["08:30"]                            # świeca 08:30–08:45 ET
        if not (b.l <= mo <= b.h):                      # brak dotknięcia MO w oknie 8:30
            n_notouch += 1
            continue
        n_touch += 1
        # kierunek fade: cena nad MO (schodzi) → long; pod MO (podchodzi) → short
        if b.o > mo:
            side, sl, tp = "long", mo - SL_PT, mo + TP_PT
        elif b.o < mo:
            side, sl, tp = "short", mo + SL_PT, mo - TP_PT
        else:
            n_skip_eq += 1
            continue
        entry = mo                                      # limit na MO (gap → i tak dotknięty w świecy)
        k_deny, ex_deny, amb = simulate(side, sl, tp, bars, i0, "sl")
        k_allow, ex_allow, _ = simulate(side, sl, tp, bars, i0, "tp")
        p_deny = pnl_pt(side, entry, k_deny, ex_deny, sl, tp)
        p_allow = pnl_pt(side, entry, k_allow, ex_allow, sl, tp)
        trades.append({
            "date": str(d), "side": side, "mo": mo, "kind_deny": k_deny, "kind_allow": k_allow,
            "deny": p_deny, "allow": p_allow, "ambig": amb,
            "month": str(d)[:7],
        })

    provable = [t for t in trades if not t["ambig"]]
    for t in provable:
        t["prov"] = t["deny"]                            # deny==allow gdy nieambiwalentny

    stats = {
        "days_with_MO": n_days_mo,
        "touch": n_touch,
        "no_touch": n_notouch,
        "skip_eq": n_skip_eq,
        "no_pair": n_nopair,
        "touch_pct": (n_touch / n_days_mo * 100) if n_days_mo else 0.0,
        "long": sum(1 for t in trades if t["side"] == "long"),
        "short": sum(1 for t in trades if t["side"] == "short"),
        "deny": agg(trades, "deny"),
        "allow": agg(trades, "allow"),
        "provable": agg(provable, "prov") if provable else None,
        "ambig_count": sum(1 for t in trades if t["ambig"]),
    }
    # rozbicie miesięczne (widełki deny/allow) i long/short (deny)
    months = sorted({t["month"] for t in trades})
    stats["monthly"] = {m: {"deny": agg([t for t in trades if t["month"] == m], "deny"),
                            "allow": agg([t for t in trades if t["month"] == m], "allow")}
                        for m in months}
    stats["by_side_deny"] = {s: agg([t for t in trades if t["side"] == s], "deny")
                             for s in ("long", "short")}

    # ── raport ──
    print("=" * 70)
    print("MIDNIGHT OPEN (0:00 ET) — retest o ~8:30 NY, fade RR 4:1, SL 10 pkt MNQ")
    print("dane: mnq_15m.csv | okno 8:30 = świeca 08:30–08:45 ET (proxy ±5min) | mar–cze 2026")
    print("=" * 70)
    print(f"\n1) DOTKNIĘCIA linii 0:00 o 8:30:")
    print(f"   dni z midnight open:        {n_days_mo}")
    print(f"   dotknięć w świecy 8:30:     {n_touch}  ({stats['touch_pct']:.0f}% dni)")
    print(f"   bez dotknięcia:             {n_notouch}")
    print(f"   long (cena z góry) / short (z dołu): {stats['long']} / {stats['short']}")
    if n_skip_eq:
        print(f"   pominięte (open==MO):       {n_skip_eq}")

    def show(name, s):
        if not s:
            print(f"\n   [{name}] brak trade'ów")
            return
        print(f"\n   [{name}]  trade'y={s['n']}  WR={s['wr']:.0f}%  "
              f"PnL={s['pnl_usd']:+.0f}$ ({s['pnl_pt']:+.0f}pkt)  PF={s['pf']:.2f}  "
              f"exp={s['exp_usd']:+.1f}$ ({s['exp_R']:+.2f}R)  maxDD={s['maxdd_usd']:.0f}$")

    print(f"\n2) BACKTEST (1 kontrakt, PV={PV}$/pkt, slippage wliczony):")
    show("deny  (SL first)", stats["deny"])
    show("allow (TP first)", stats["allow"])
    show("provable        ", stats["provable"])
    print(f"\n   trade'y niejednoznaczne intrabar (SL i TP w tej samej świecy 15m): {stats['ambig_count']}")

    print(f"\n   long  (deny): ", end="")
    show("", stats["by_side_deny"]["long"])
    print(f"   short (deny): ", end="")
    show("", stats["by_side_deny"]["short"])

    print(f"\n3) MIESIĘCZNIE (deny → allow, PnL $):")
    for m in months:
        md, ma = stats["monthly"][m]["deny"], stats["monthly"][m]["allow"]
        print(f"   {m}: {md['pnl_usd']:+.0f}$ → {ma['pnl_usd']:+.0f}$   ({md['n']} tr, WR {md['wr']:.0f}%→{ma['wr']:.0f}%)")

    # werdykt
    dprof = stats["deny"]["pf"] > 1.0 and stats["deny"]["exp_pt"] > 0
    aprof = stats["allow"]["pf"] > 1.0 and stats["allow"]["exp_pt"] > 0
    print(f"\n4) WERDYKT (profitable?):")
    print(f"   deny  (pesymistyczny): {'TAK' if dprof else 'NIE'}  (PF {stats['deny']['pf']:.2f})")
    print(f"   allow (optymistyczny): {'TAK' if aprof else 'NIE'}  (PF {stats['allow']['pf']:.2f})")
    print(f"   → wynik orientacyjny (próba {stats['deny']['n']} tr, 15m proxy, mar–cze). "
          f"Realny między deny a allow.")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "mo830.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"stats": stats, "trades": trades}, f, indent=2, default=str)
    print(f"\n   zapisano: site/mo830.json  ({len(trades)} trade'ów)")


if __name__ == "__main__":
    main()
