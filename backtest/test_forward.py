"""Testy: kawalki 15m po dziurach (engine.run_segmented), scalanie eksportow (merge_data.py)
i test forward (validate_forward.py)."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))

# Swiece MNQ (data/*.csv) nie sa w publicznym repo (licencja danych CME/TradingView) —
# testy na realnych danych sie wtedy pomijaja zamiast padac.
needs_data = pytest.mark.skipif(not (ROOT / "data" / "mnq_15m.csv").exists(),
                                reason="market data (data/*.csv) not included")

import config
import engine
import merge_data as md
import validate_forward as vf
from engine import Bar, Trade, load_csv, make_config


def _bars(ts_list):
    return [Bar(t, 1, 1, 1, 1, 0) for t in ts_list]


def _row(o, h=None, l=None, c=None):
    return {"open": str(o), "high": str(h or o), "low": str(l or o), "close": str(c or o), "volume": "1"}


# ---------- segmentacja ----------

def test_split_segments_cuts_only_long_gaps():
    day = 86400
    ts = [0, 900, 1800, 3 * day, 3 * day + 900, 20 * day, 20 * day + 900]   # weekend 3 dni = OK
    segs = engine.split_segments(_bars(ts))
    assert [[b.ts for b in s] for s in segs] == [ts[:5], ts[5:]]


@needs_data
def test_run_segmented_single_segment_is_identical():
    """Jeden ciagly kawalek = dokladnie run_entry_zone (stare wyniki sie nie zmieniaja)."""
    data = tuple(load_csv(ROOT / "data" / "archive" / f"mnq_{tf}_do_2026-06-11.csv")
                 for tf in ("15m", "1h", "4h", "1d"))
    cfg = make_config(config)
    a, *_ = engine.run_entry_zone(cfg, *data)
    b, _f, _s, bt = engine.run_segmented(cfg, *data)
    assert [(t.entry_ts, t.pnl) for t in a] == [(t.entry_ts, t.pnl) for t in b]
    assert len(bt.segments) == 1


@needs_data
def test_run_segmented_reproduces_frozen_headline_on_merged_data():
    """Stara proba jako pierwszy kawalek scalonych danych daje dalej $2507.29 / 25 tr."""
    data = tuple(load_csv(ROOT / "data" / f"mnq_{tf}.csv") for tf in ("15m", "1h", "4h", "1d"))
    tr, *_ = engine.run_segmented(make_config(config), *data)
    is_tr, _fwd = vf.split(tr, vf.freeze_ts())
    assert len(is_tr) == 25
    assert abs(sum(t.pnl for t in is_tr) - 2507.29) < 0.01


def test_run_segmented_drops_warmup_entries(monkeypatch):
    day = 86400
    m15 = _bars([i * 900 for i in range(200)] + [30 * day + i * 900 for i in range(200)])

    def fake_zone(cfg, seg, h1, h4, d1):
        # po jednym "wejsciu" na 10. barze kazdego kawalka
        t = Trade("long", seg[10].ts, 1.0, 0.0, 2.0, result="tp", pnl=1.0)

        class B:
            fvgs, nwogs, key_opens, shadow_trades = [], [], [], []
        return [t], {"entries": 1}, [], B()

    monkeypatch.setattr(engine, "run_entry_zone", fake_zone)
    tr, fn, _s, bt = engine.run_segmented(None, m15, [], [], [], warmup_bars=96)
    # pierwszy kawalek bez rozbiegu (jak dotad), drugi: wejscie na barze 10 < 96 odrzucone
    assert [t.entry_ts for t in tr] == [m15[10].ts]
    assert fn == {"entries": 2} and len(bt.segments) == 2


# ---------- scalanie ----------

def test_merge_later_layer_wins_and_ignores_unfinished_last_bar():
    old = {1: _row(10), 2: _row(11), 3: _row(12, 12, 12, 12)}   # bar 3 = niedomkniety przy eksporcie
    new = {2: _row(11), 3: _row(12, 15, 11, 14), 4: _row(13)}
    out, rep = md.merge([old, new])
    assert sorted(out) == [1, 2, 3, 4]
    assert out[3]["high"] == "15"            # wygrywa swiezszy eksport
    assert rep == [(0, []), (1, [])]         # roznica tylko na ostatnim barze bazy = nie rozjazd


def test_merge_reports_series_mismatch():
    old = {1: _row(10), 2: _row(11), 3: _row(12)}
    other = {1: _row(10), 2: _row(99)}       # inny kontrakt na tym samym ts
    _out, rep = md.merge([old, other])
    assert rep[1] == (1, [2])


def test_clip_is_half_open_and_gaps():
    rows = {t: _row(1) for t in (5, 10, 15)}
    assert sorted(md.clip(rows, 10, 15)) == [10]
    assert sorted(md.clip(rows, None, None)) == [5, 10, 15]
    assert md.gaps([0, 900, 10 * 86400]) == [(900, 10 * 86400)]


# ---------- forward ----------

def _st(pnl, trades=25):
    return {"pnl_total": pnl, "trades": trades}


def test_verdict_requires_both_brackets_and_stable_months():
    m_ok = {"a": {"pnl": 1}, "b": {"pnl": -1}}
    assert vf.verdict({"deny": _st(10), "allow": _st(20), "provable": _st(10)}, m_ok)[0] == "GO*"
    assert vf.verdict({"deny": _st(-1), "allow": _st(20), "provable": _st(10)}, m_ok)[0] == "NO-GO"
    m_bad = {"a": {"pnl": 5}, "b": {"pnl": -1}, "c": {"pnl": -1}}
    assert vf.verdict({"deny": _st(1), "allow": _st(2), "provable": _st(1)}, m_bad)[0].startswith("NO-GO")
    small = vf.verdict({"deny": _st(1), "allow": _st(2), "provable": _st(1, trades=5)}, m_ok)[0]
    assert "orientacyjny" in small


def test_split_by_freeze_is_disjoint_and_drops_open():
    tr = [Trade("long", ts, 1, 0, 2, result="tp") for ts in (5, 10, 11)] + [Trade("long", 12, 1, 0, 2)]
    a, b = vf.split(tr, 10)
    assert [t.entry_ts for t in a] == [5, 10] and [t.entry_ts for t in b] == [11]


def test_buy_hold_skips_roll_jump():
    bars = [Bar(0, 100, 100, 100, 100, 0), Bar(900, 110, 110, 110, 110, 0),
            Bar(1800, 50, 50, 50, 50, 0)]   # bar 1800 = przeskok na rolce
    assert vf.buy_hold_pct(bars, 0, 1800, skip_ts=(1800,)) == 10.0


# ---------- bootstrap 95% CI expectancy ----------

def test_bootstrap_ci_is_deterministic_and_brackets_mean():
    pnls = [100, -50, 200, -50, -50, 300, -50, 40]
    a, b = vf.bootstrap_ci(pnls, n_boot=2000, seed=7), vf.bootstrap_ci(pnls, n_boot=2000, seed=7)
    assert a == b
    assert a["lo"] < a["mean"] < a["hi"] and a["n"] == 8
    assert a["mean"] == round(sum(pnls) / len(pnls), 2)


def test_bootstrap_ci_needs_two_trades():
    assert vf.bootstrap_ci([50.0])["lo"] is None
    assert vf.bootstrap_ci([])["mean"] is None
