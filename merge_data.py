"""Skleja eksporty z TradingView w data/mnq_{15m,1h,4h,1d}.csv (stdlib only).

    python3 merge_data.py            # scal + raport nakładek i dziur
    python3 merge_data.py --check    # tylko raport, bez zapisu

Źródła nakładane są po kolei; przy tym samym ts wygrywa PÓŹNIEJSZE (świeższy eksport).
Zanim źródło zostanie wklejone, jego bary porównywane są z tym, co już jest: jeśli OHLC na
wspólnych ts się nie zgadza, to znaczy, że to INNA seria (inny kontrakt, back-adjust) i skrypt
staje, zamiast po cichu mieszać dwa wykresy. Wyjątek: ostatni bar poprzedniego źródła — w chwili
eksportu bywał jeszcze niedomknięty (sprawdzone: dokładnie 1 rozjazd na 1h/4h/1d, zawsze ten).

Skąd okno MNQU2026: TV oddaje ~5000 barów 15m wstecz, więc MNQ1! sięga dziś tylko do 02.08.
Wygasły kontrakt wrześniowy ma własne 5000 barów (od 30.06). MNQ1! jest nieadjustowany, więc
między rolkami to dokładnie kontrakt frontowy — zgodność MNQU z MNQ1! sprawdzona co do ticka
w oknie 14.06 22:00 → 14.09 22:00 UTC (1506 barów 1h, 2836 barów 15m, 0 rozjazdów). Poza tym oknem
MNQU NIE jest MNQ1! i nie wolno go używać.
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# okno, w którym MNQU2026 = MNQ1! (rolka czerwcowa → rolka wrześniowa), ts w sekundach UTC
MNQU_FRONT = (1781474400, 1789423200)   # 2026-06-14 22:00 → 2026-09-14 22:00 UTC (wyłącznie)

# (plik, od_ts, do_ts) — None = bez ograniczenia; kolejność = priorytet rosnąco
SOURCES = {
    "15m": [("archive/mnq_15m_do_2026-06-11.csv", None, None),
            ("raw/mnqu_15m_2026-10-18.csv", *MNQU_FRONT),
            ("raw/mnq_15m_2026-10-18.csv", None, None),
            ("raw/mnq_15m_2026-11-15.csv", None, None)],
    **{tf: [(f"archive/mnq_{tf}_do_2026-06-11.csv", None, None),
            (f"raw/mnq_{tf}_2026-10-18.csv", None, None),
            (f"raw/mnq_{tf}_2026-11-15.csv", None, None)] for tf in ("1h", "4h", "1d")},
}
OHLC = ("open", "high", "low", "close")
GAP_DAYS = 4          # dłuższa przerwa niż weekend+święto = dziura w danych


def read_rows(path) -> dict[int, dict]:
    with open(path, newline="") as f:
        return {int(r["time"]): r for r in csv.DictReader(f)}


def clip(rows: dict[int, dict], lo, hi) -> dict[int, dict]:
    return {t: r for t, r in rows.items() if (lo is None or t >= lo) and (hi is None or t < hi)}


def mismatches(base: dict[int, dict], new: dict[int, dict], tol: float = 0.01) -> list[int]:
    """ts wspólne, na których OHLC się różni — bez ostatniego baru bazy (mógł być niedomknięty)."""
    if not base:
        return []
    last = max(base)
    return sorted(t for t in set(base) & set(new) if t != last and
                  max(abs(float(base[t][k]) - float(new[t][k])) for k in OHLC) > tol)


def merge(layers: list[dict[int, dict]]) -> tuple[dict[int, dict], list[tuple[int, list[int]]]]:
    """Nakłada warstwy po kolei (późniejsza wygrywa). Zwraca (wynik, [(nr_warstwy, rozjazdy)])."""
    out: dict[int, dict] = {}
    report = []
    for i, rows in enumerate(layers):
        report.append((i, mismatches(out, rows)))
        out.update(rows)
    return out, report


def gaps(ts: list[int], max_gap_s: int = GAP_DAYS * 86400) -> list[tuple[int, int]]:
    ts = sorted(ts)
    return [(a, b) for a, b in zip(ts, ts[1:]) if b - a > max_gap_s]


def _d(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="tylko raport, bez zapisu")
    args = ap.parse_args()

    ok = True
    merged = {}
    for tf, srcs in SOURCES.items():
        layers = [clip(read_rows(DATA / p), lo, hi) for p, lo, hi in srcs]
        out, rep = merge(layers)
        merged[tf] = out
        print(f"{tf}: {len(out)} barów  {_d(min(out))} -> {_d(max(out))} UTC")
        for (i, bad), (p, _, _) in zip(rep, srcs):
            n = len(layers[i])
            print(f"   + {p:<38} {n:>6} barów  rozjazdów na nakładce: {len(bad)}")
            if bad:
                ok = False
                print(f"     ! pierwszy {_d(bad[0])}, ostatni {_d(bad[-1])} — inna seria?")
        for a, b in gaps(list(out)):
            print(f"   DZIURA: {_d(a)} -> {_d(b)} UTC ({(b - a) / 86400:.1f} dni)")

    if not ok:
        raise SystemExit("STOP: rozjazdy OHLC na nakładce — nic nie zapisano.")
    if args.check:
        return
    for tf, out in merged.items():
        with open(DATA / f"mnq_{tf}.csv", "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")   # jak w eksportach TV — inaczej diff calego pliku
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            for t in sorted(out):
                r = out[t]
                w.writerow([t, r["open"], r["high"], r["low"], r["close"], r["volume"]])
    print("Zapisano data/mnq_{15m,1h,4h,1d}.csv")


if __name__ == "__main__":
    main()
