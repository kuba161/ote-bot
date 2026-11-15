"""Testy walidacji walk-forward (validate_wf.py): podzial okien, brak leak, wybor plateau."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))            # validate_wf.py
sys.path.insert(0, str(ROOT / "backtest"))  # engine / config

# Swiece MNQ nie sa w publicznym repo (licencja danych) — wtedy test integracyjny sie pomija.
needs_data = pytest.mark.skipif(not (ROOT / "data" / "mnq_15m.csv").exists(),
                                reason="market data (data/*.csv) not included")

import config
import validate_wf as wf
from engine import Bar, Trade, load_csv, make_config


def _row(val, tr_pnl, te_pnl=0.0):
    """Minimalny wiersz skanu (plateau/argmax/fragility patrza tylko na pnl_total)."""
    return {"val": val,
            "train": {"pnl_total": tr_pnl, "profit_factor": None},
            "test": {"pnl_total": te_pnl, "profit_factor": None}}


# ---------- okna ----------

def test_split_ts_position_and_clamp():
    m15 = [Bar(1000 + i * 900, 1, 1, 1, 1, 0) for i in range(10)]
    assert wf.split_ts(m15, 0.6) == m15[6].ts
    # clamp: frac=0 -> nie indeks 0 (min 1), frac>=1 -> ostatni dozwolony (len-1)
    assert wf.split_ts(m15, 0.0) == m15[1].ts
    assert wf.split_ts(m15, 1.0) == m15[9].ts


def test_in_window_half_open():
    def tr(ts):
        return Trade("long", ts, 100.0, 99.0, 102.0)
    trades = [tr(10), tr(20), tr(30), tr(40)]
    got = [t.entry_ts for t in wf.in_window(trades, 20, 40)]
    assert got == [20, 30]   # [lo, hi): 20 wlacznie, 40 wylacznie


# ---------- plateau / argmax / fragility ----------

def test_plateau_prefers_broad_over_sharp_peak():
    # ostry pik na idx1 (90, sasiedzi 10/10) vs plateau idx3-5 (50/55/52)
    rows = [_row(0, 10), _row(1, 90), _row(2, 10), _row(3, 50), _row(4, 55), _row(5, 52)]
    assert wf.argmax_idx(rows) == 1          # goly argmax lapie pik
    assert wf.plateau_idx(rows) == 4         # plateau wybiera srodek plaskowyzu
    assert wf.plateau_idx(rows) != wf.argmax_idx(rows)


def test_fragility_sign():
    # default = pik (sasiedzi nizsi) -> fragility dodatnia (kruche)
    peak = [_row(0, 10), _row(1, 100), _row(2, 10)]
    assert wf.fragility(peak, 1) > 0
    # default = dolina (sasiedzi wyzsi) -> fragility ujemna (stabilne/anty-kruche)
    valley = [_row(0, 100), _row(1, 10), _row(2, 100)]
    assert wf.fragility(valley, 1) < 0
    # brzeg bez obu sasiadow liczony z jednego sasiada (nie None)
    assert wf.fragility(peak, 0) is not None


def test_train_pick_holds_uses_test_median():
    # argmax train = idx2; jego test ponizej mediany testu -> nie trzyma
    rows = [_row(0, 1, te_pnl=100), _row(1, 2, te_pnl=50),
            _row(2, 99, te_pnl=-100), _row(3, 3, te_pnl=80)]
    assert wf.argmax_idx(rows) == 2
    assert wf.train_pick_holds(rows, 2) is False
    # gdy najlepszy-na-train ma tez najlepszy test -> trzyma
    rows2 = [_row(0, 1, te_pnl=10), _row(1, 99, te_pnl=99), _row(2, 2, te_pnl=20)]
    assert wf.train_pick_holds(rows2, 1) is True


# ---------- integration: brak leak + partycja na realnych danych ----------

def _real_data():
    base = ROOT / "data"
    return tuple(load_csv(base / f"mnq_{tf}.csv") for tf in ("15m", "1h", "4h", "1d"))


@needs_data
def test_split_no_leak_and_partition():
    data = _real_data()
    m15 = data[0]
    t0, t1 = m15[0].ts, m15[-1].ts
    sp = wf.split_ts(m15, 0.6)
    cfg = make_config(config, {})
    _, _, train, test = wf.split_stats(cfg, data, t0, sp, t1)
    full = wf.run_to(cfg, data, t1)
    # brak leak: zaden trade testowy nie ma wejscia przed granica; train nie po granicy
    assert train and test
    assert all(t.entry_ts < sp for t in train)
    assert all(t.entry_ts >= sp for t in test)
    # rozlaczny podzial pokrywa caly backtest (po liczbie i po PnL)
    assert len(train) + len(test) == len(full)
    assert abs(sum(t.pnl for t in train) + sum(t.pnl for t in test)
               - sum(t.pnl for t in full)) < 1e-6
