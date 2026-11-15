"""Testy benchmarku losowych wejsc (validate_random.py) na syntetycznych barach z test_engine."""
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))

import validate_random as vr
from engine import killzone
from test_engine import M15, TS0, _bt, _prefix, mk


def _bars(n=40):
    # prefix z kompletna noga + spokojny ciag barow, na ktorych losowy trader moze wchodzic
    out = _prefix()
    for k in range(11, 11 + n):
        o = 150 + (k % 5)
        out.append(mk(k, o, o + 6, o - 6, o + 1))
    return out


def test_zero_probability_means_no_trades():
    bt = _bt(_bars())
    elig = set(vr.eligible_bars(bt, bt.cfg))
    assert elig and vr.random_run(bt, elig, 0.0, random.Random(1)) == []


def test_same_seed_same_trades():
    bt = _bt(_bars())
    elig = set(vr.eligible_bars(bt, bt.cfg))
    a = vr.random_run(bt, elig, 0.5, random.Random(3))
    b = vr.random_run(bt, elig, 0.5, random.Random(3))
    assert [(t.entry_ts, t.side, t.pnl) for t in a] == [(t.entry_ts, t.side, t.pnl) for t in b]
    assert a, "przy p=0.5 na 40 barach powinno byc jakies wejscie"


def test_entries_only_in_allowed_sessions():
    bt = _bt(_bars(120), SESSION_FILTER=True, TRADE_SESSIONS=("London",))
    elig = vr.eligible_bars(bt, bt.cfg)
    assert elig and all(killzone(bt.m15[i].ts) == "London" for i in elig)
    tr = vr.random_run(bt, set(elig), 1.0, random.Random(5))
    assert all(killzone(t.entry_ts) == "London" for t in tr)


def test_percentile_of_handles_ties_and_bounds():
    assert vr.percentile_of(5, [1, 2, 3]) == 100.0
    assert vr.percentile_of(0, [1, 2, 3]) == 0.0
    assert vr.percentile_of(2, [1, 2, 3]) == 50.0
