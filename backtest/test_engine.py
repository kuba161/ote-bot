"""Testy jednostkowe portu logiki Pine na syntetycznych barach 15m."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import config
import engine
from engine import (Backtester, Bar, compute_fvgs, compute_key_opens,
                    compute_leg_states, ema_series)

TS0 = 1772420400  # 2026-03-01 22:00 ET (niedziela); bar i=8 zaczyna sie o 00:00 ET
M15 = 900


def mk(idx: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(TS0 + idx * M15, o, h, l, c, 0.0)


def flat(n: int, price: float = 100.0, start: int = 0) -> list[Bar]:
    return [mk(start + i, price, price + 1, price - 1, price) for i in range(n)]


# ---------- leg / pivoty ----------

def test_pivot_high_confirms_after_len_bars():
    piv = 2
    bars = flat(2) + [mk(2, 100, 120, 99, 101)] + flat(4, start=3)
    states = compute_leg_states(bars, piv)
    # pivot na i=2 potwierdzony na barze 4 (piv barow pozniej), stan PO barze 4
    assert states[3].sw_h is None
    assert states[4].sw_h == 120
    assert states[4].sw_ht == bars[2].ts
    # runMin po potwierdzeniu = lowest z ostatnich piv+1 barow
    assert states[4].run_min == min(b.l for b in bars[2:5])


def test_running_extreme_updates_after_pivot_low():
    piv = 2
    bars = flat(2) + [mk(2, 100, 101, 80, 100),
                      mk(3, 100, 102, 99, 101), mk(4, 101, 103, 100, 102),
                      mk(5, 102, 110, 101, 109), mk(6, 109, 115, 108, 114)]
    states = compute_leg_states(bars, piv)
    assert states[4].sw_l == 80          # pivot low z i=2 potwierdzony na i=4
    assert states[4].run_max == 103      # hh z len+1 barow przy potwierdzeniu
    assert states[5].run_max == 110      # kroczace maksimum rosnie
    assert states[6].run_max == 115


# ---------- FVG ----------

def test_fvg_creation_mitigation_inversion():
    # bull FVG na i=2: high[0]=101 < low[2]=115, rozmiar 14 >= 8
    bars = [mk(0, 100, 101, 99, 100), mk(1, 105, 112, 104, 111),
            mk(2, 116, 120, 115, 119),
            mk(3, 119, 121, 118, 120),          # nic
            mk(4, 120, 121, 114, 118),          # touch (low<=top) -> mitigated
            mk(5, 118, 119, 95, 96)]            # close < bot -> inverted
    fvgs = compute_fvgs(bars, 8.0)
    assert len(fvgs) == 1
    g = fvgs[0]
    assert g.bull and g.top == 115 and g.bot == 101 and g.created == 2
    assert g.mitigated == 4
    assert g.inverted == 5


def test_fvg_min_size_filter():
    bars = [mk(0, 100, 101, 99, 100), mk(1, 103, 104, 102, 103),
            mk(2, 105, 106, 104.5, 105)]   # gap 101->104.5 = 3.5 < 8
    assert compute_fvgs(bars, 8.0) == []


# ---------- EMA / bias [1] ----------

def test_htf_ema_uses_previous_closed_bar():
    closes = [float(i) for i in range(1, 50)]
    h1 = [Bar(TS0 + i * 3600, c, c, c, c, 0) for i, c in enumerate(closes)]
    htf = engine.HtfEma(h1, 20)
    t_inside_bar_30 = TS0 + 30 * 3600 + 1800
    assert htf.at(t_inside_bar_30) == htf.ema[29]   # bar poprzedzajacy ten z t


def test_ema_seed_sma():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    e = ema_series(closes, 3)
    assert e[0] is None and e[1] is None
    assert abs(e[2] - 2.0) < 1e-9            # SMA(3)
    assert abs(e[3] - (0.5 * 4 + 0.5 * 2.0)) < 1e-9


# ---------- key opens ----------

def test_key_open_detection_et():
    bars = [mk(i, 100, 101, 99, 100) for i in range(200)]
    kos = compute_key_opens(bars, ("10:00",))
    assert kos, "brak wykrytych key opens"
    for ko in kos:
        assert engine._et(ko.ts).strftime("%H:%M") == "10:00"


# ---------- e2e ----------
# Wspolny uklad barow (piv=2): pivot low 170 (i=2), rajd do pivot high 200 (i=6),
# zjazd z bearish FVG [167,180] (created i=9), run_min=140 (i=10), korekta w gore (i=11).
# Noga short: H=200, L=140. ENTRY_FIB=0.5 -> E=170 (w FVG, ponizej EMA15 ~172.3).

def _prefix():
    return [mk(0, 180, 181, 175, 178),
            mk(1, 178, 179, 174, 176),
            mk(2, 175, 176, 170, 174),    # pivot low 170
            mk(3, 175, 182, 174, 181),
            mk(4, 182, 190, 181, 189),    # potwierdzenie pivot low
            mk(5, 190, 195, 189, 194),
            mk(6, 195, 200, 194, 197),    # pivot high 200
            mk(7, 196, 197, 180, 181),
            mk(8, 178, 179, 168, 169),    # potwierdzenie pivot high (bar 00:00 ET, open 178)
            mk(9, 166, 167, 150, 152),    # bearish FVG: 180->167 (13 pt)
            mk(10, 151, 152, 140, 142)]   # run_min = 140


def _htf_falling():
    h1 = [Bar(TS0 - 100 * 3600 + i * 3600, 300.0 - i, 300.0 - i, 300.0 - i, 300.0 - i, 0)
          for i in range(100)]
    d1 = [Bar(TS0 - 100 * 86400 + i * 86400, 300.0 - i, 300.0 - i, 300.0 - i, 300.0 - i, 0)
          for i in range(100)]
    return h1, d1


def _cfg(**over):
    class C:
        pass
    for k in dir(config):
        if k.isupper():
            setattr(C, k, getattr(config, k))
    for k, v in over.items():
        setattr(C, k, v)
    return C


def _bt(bars, **over):
    # e2e walidują mechanike pod biasem EMA20 (bary HTF monotoniczne, bez pivotow);
    # strukture (BOS/HH-HL) pokrywaja osobne testy ponizej. Wylaczamy nowe domyslne filtry
    # (sesja) i pinujemy 4xTF, zeby e2e bylo niezalezne od zmian defaultow strategii.
    over.setdefault("BIAS_METHOD", "EMA20")
    over.setdefault("SESSION_FILTER", False)
    over.setdefault("EXIT_MODE", "fib")
    over.setdefault("SIZING_MODE", "fixed")
    over.setdefault("BIAS_TFS", ("15m", "1h", "4h", "1d"))
    cfg = _cfg(PIVOT_LEN=2, EMA_LEN=10, ENTRY_FIB=0.5, TP_FIB=0.25,
               SLIPPAGE_TICKS_ENTRY=0, SLIPPAGE_TICKS_STOP=0, COMMISSION_RT=0.0, **over)
    h1, d1 = _htf_falling()
    return Backtester(cfg, bars, h1, h1, d1)


def test_e2e_short_trade_hits_tp():
    bars = _prefix() + [mk(11, 160, 171, 158, 168),   # crossuje E=170 -> fill (w FVG)
                        mk(12, 168, 169, 154, 156)]   # low<=TP=155 -> TP
    trades = _bt(bars).run()
    assert len(trades) == 1, f"oczekiwano 1 trade: {trades}"
    t = trades[0]
    assert t.side == "short" and t.filter == "fvg" and t.result == "tp"
    assert abs(t.entry - 170.0) < 1e-9
    assert abs(t.tp - 155.0) < 1e-9 and abs(t.sl - 200.0) < 1e-9
    assert abs(t.pnl - (170 - 155) * 2.0) < 1e-9


def test_e2e_no_trade_without_filter():
    """Bez FVG (gap < 8pt) i poza zasiegiem key open -> sygnal odrzucony filtrem."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    bars[9] = mk(9, 166, 175, 150, 152)   # gap 180->175 = 5 pt < 8 -> brak FVG
    assert _bt(bars).run() == []


def test_e2e_sl_first_on_entry_bar():
    """Bar wejscia siega tez SL -> konserwatywnie strata."""
    bars = _prefix() + [mk(11, 160, 201, 158, 170)]   # fill E=170 oraz high>=SL=200
    trades = _bt(bars).run()
    assert len(trades) == 1
    assert trades[0].result == "sl"
    assert trades[0].pnl < 0


def test_gap_through_stop_exits_at_market_not_sl_price():
    """Luka przez SL -> wyjscie po open bara, nie po (lepszej) cenie SL."""
    bt = _bt(_prefix() + [mk(11, 160, 171, 158, 168)])
    # long z gap-fillem na open ponizej SL (scenariusz niedzielnego otwarcia)
    pos = engine.Trade("long", TS0, entry=25004.0, sl=25222.0, tp=25308.0)
    out = []
    res = bt._manage(pos, Bar(TS0 + M15, 25004.0, 25050.0, 24900.0, 24950.0, 0), out, entry_bar=True)
    assert res is None and out[0].result == "sl"
    assert abs(out[0].exit - 25004.0) < 1e-9     # open, NIE 25222
    assert abs(out[0].pnl) < 1e-9
    # short trzymany przez weekend, open powyzej SL -> wyjscie po open
    pos2 = engine.Trade("short", TS0, entry=190.0, sl=200.0, tp=170.0)
    out2 = []
    bt._manage(pos2, Bar(TS0 + M15, 210.0, 212.0, 205.0, 208.0, 0), out2)
    assert out2[0].result == "sl"
    assert abs(out2[0].exit - 210.0) < 1e-9
    assert out2[0].pnl < 0


def test_entry_bar_tp_denied_carries_to_next_bar():
    """ENTRY_BAR_TP=deny: dotkniecie TP na barze wejscia nie konczy pozycji."""
    bars = _prefix() + [mk(11, 160, 171, 150, 168),    # crossuje E=170 ORAZ TP=155 intrabar
                        mk(12, 168, 169, 154, 156)]    # TP dopiero tutaj
    trades = _bt(bars, ENTRY_BAR_TP="deny").run()
    assert len(trades) == 1
    t = trades[0]
    assert t.result == "tp"
    assert t.exit_ts == bars[12].ts


def test_e2e_one_entry_per_leg():
    """Po SL na nodze brak re-entry, dopoki nie powstanie nowa noga."""
    bars = _prefix() + [mk(11, 160, 201, 158, 170),   # trade 1: SL
                        mk(12, 168, 171, 158, 168),   # ponowny cross E -> ta sama noga, brak trade'u
                        mk(13, 168, 169, 154, 156)]
    trades = _bt(bars).run()
    assert len(trades) == 1


# ---------- MAE/MFE + post-exit probe ----------

def test_mae_mfe_tracked_over_trade_life():
    """MAE/MFE z pelnego zakresu h/l barow od wejscia do wyjscia wlacznie."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168),   # entry 170; adverse +1, favor 12
                        mk(12, 168, 169, 154, 156)]   # favor 16 -> TP
    t = _bt(bars).run()[0]
    assert abs(t.mae_pt - 1.0) < 1e-9
    assert abs(t.mfe_pt - 16.0) < 1e-9
    assert abs(t.risk_pt - 30.0) < 1e-9   # |170 - 200| zamrozone przy wejsciu


def test_post_exit_tp_probe_counts_bars():
    """post_tp_bars: za ile barow od SL cena dotknela oryginalnego TP (0 = bar SL)."""
    # k=2: SL na barze 11, TP=155 dotkniete dopiero na barze 13
    bars = _prefix() + [mk(11, 160, 201, 158, 170),
                        mk(12, 168, 169, 160, 165),
                        mk(13, 168, 169, 154, 156)]
    t = _bt(bars).run()[0]
    assert t.result == "sl" and t.post_tp_bars == 2
    # k=0: bar SL sam dotyka TP (kandydat na niejednoznacznosc intrabar)
    bars0 = _prefix() + [mk(11, 160, 201, 154, 170)]
    t0 = _bt(bars0).run()[0]
    assert t0.result == "sl" and t0.post_tp_bars == 0
    # None: brak dotkniecia TP w oknie POST_EXIT_BARS
    barsn = _prefix() + [mk(11, 160, 201, 158, 170)] + \
            [mk(12 + i, 168, 169, 160, 165) for i in range(14)]
    tn = _bt(barsn).run()[0]
    assert tn.result == "sl" and tn.post_tp_bars is None


# ---------- shadow trades ----------

def test_shadow_trade_recorded_on_filter_reject():
    """Sygnal odrzucony filtrem trafia do shadow_trades i jest symulowany identycznie."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    bars[9] = mk(9, 166, 175, 150, 152)   # gap 5 pt < 8 -> brak FVG -> brak filtra
    bt = _bt(bars)
    assert bt.run() == []
    assert len(bt.shadow_trades) == 1
    sp = bt.shadow_trades[0]
    assert sp.filter == "none" and sp.result == "tp"
    assert abs(sp.entry - 170.0) < 1e-9 and abs(sp.pnl - 30.0) < 1e-9


def test_shadow_one_per_leg_and_not_in_real_trades():
    """Max 1 shadow na noge mimo wielokrotnych crossow; brak wplywu na realne trade'y."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168),   # cross 1 -> shadow
                        mk(12, 168, 171, 158, 168),   # cross 2, ta sama noga -> bez shadow
                        mk(13, 168, 169, 154, 156)]   # TP shadow
    bars[9] = mk(9, 166, 175, 150, 152)   # brak FVG
    bt = _bt(bars)
    assert bt.run() == []
    assert len(bt.shadow_trades) == 1
    assert bt.funnel["shadow"] == 1
    assert bt.funnel["rej_filter"] == 2


# ---------- ENTRY_BAR_TP = "provable" ----------

def test_entry_bar_tp_provable_awards_fill_at_open():
    """Fill na open + SL nietkniety -> TP na barze wejscia jest pewny (dowolna sciezka)."""
    bars = _prefix() + [mk(11, 172, 173, 154, 156)]   # open 172 >= E=170, low <= TP=155
    trades = _bt(bars, ENTRY_BAR_TP="provable").run()
    assert len(trades) == 1
    t = trades[0]
    assert t.fill_at_open and t.result == "tp"
    assert t.exit_ts == bars[11].ts
    assert abs(t.exit - 155.0) < 1e-9 and abs(t.pnl - 34.0) < 1e-9


def test_entry_bar_tp_provable_denies_midbar_fill():
    """Fill w srodku bara -> sekwencja intrabar nieznana -> TP dopiero od nastepnego bara."""
    bars = _prefix() + [mk(11, 160, 171, 150, 168),   # fill 170 w srodku bara, TP intrabar
                        mk(12, 168, 169, 154, 156)]
    trades = _bt(bars, ENTRY_BAR_TP="provable").run()
    assert len(trades) == 1
    assert trades[0].result == "tp"
    assert trades[0].exit_ts == bars[12].ts   # nie na barze wejscia


def test_entry_bar_tp_provable_denies_when_sl_touched():
    """Fill na open, ale bar dotknal tez SL -> niejednoznaczne -> SL (konserwatywnie)."""
    bars = _prefix() + [mk(11, 172, 201, 154, 156)]   # open-fill, high >= SL=200, low <= TP
    trades = _bt(bars, ENTRY_BAR_TP="provable").run()
    assert len(trades) == 1
    assert trades[0].result == "sl"


# ---------- gap-guard ----------

def test_gap_guard_skips_entry_beyond_sl_and_consumes_leg():
    """Fill juz za SL (gap przez limit i SL) -> brak wejscia, noga skonsumowana."""
    bars = _prefix() + [mk(11, 205, 206, 195, 198),   # open 205 > SL=200
                        mk(12, 198, 199, 190, 195)]
    # szeroki key open, zeby filtr przepuszczal fill=205 (bar 00:45 ET, open 00:00 = 178)
    bt = _bt(bars, KEY_OPEN_MAX_TICKS=200)
    assert bt.run() == []
    assert bt.funnel["rej_gap_guard"] == 1
    assert bt.funnel["entries"] == 0
    # bez guarda: martwe wejscie na open i natychmiastowy scratch (stare zachowanie #11/#12)
    bt2 = _bt(bars, KEY_OPEN_MAX_TICKS=200, GAP_GUARD=False)
    trades = bt2.run()
    assert len(trades) == 1
    assert trades[0].result == "sl"
    assert abs(trades[0].exit - 205.0) < 1e-9   # wyjscie po open, nie po SL
    assert abs(trades[0].pnl) < 1e-9


# ---------- MIN_LEG_PT + SL_FIB ----------

def test_min_leg_filter_skips_then_allows_grown_leg():
    """Noga ponizej progu odrzucona BEZ konsumpcji; po urosnieciu może zagrac."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168),    # noga 60 pt < 70 -> rej_min_leg
                        mk(12, 130, 131, 120, 122),    # run_min 120 -> noga 80 pt
                        mk(13, 150, 162, 148, 155),    # E=160, fill
                        mk(14, 152, 153, 138, 142)]    # TP=140
    bt = _bt(bars, MIN_LEG_PT=70.0, KEY_OPEN_MAX_TICKS=200, KEY_OPEN_WINDOW_MIN=600)
    trades = bt.run()
    assert bt.funnel["rej_min_leg"] >= 1
    assert len(trades) == 1
    assert abs(trades[0].entry - 160.0) < 1e-9
    assert trades[0].result == "tp"


def test_sl_fib_buffer_widens_stop():
    """SL_FIB=1.1: stop za swingiem przezywa sweep, ktory przy 1.0 daje SL."""
    bars = _prefix() + [mk(11, 160, 201, 158, 168),   # high 201: sweep starego SL=200
                        mk(12, 168, 169, 154, 156)]   # TP
    t_buf = _bt(bars, SL_FIB=1.1).run()[0]
    assert abs(t_buf.sl - 206.0) < 1e-9   # 140 + 1.1*60
    assert t_buf.result == "tp"
    assert abs(t_buf.risk_pt - 36.0) < 1e-9
    t_std = _bt(bars, SL_FIB=1.0).run()[0]
    assert abs(t_std.sl - 200.0) < 1e-9   # regresja: 1.0 = origin swing jak dotad
    assert t_std.result == "sl"


# ---------- break-even ----------

def test_be_moves_sl_to_entry_after_closed_bar_not_entry_bar():
    """BE zbroi sie dopiero po DOMKNIETYM barze (nie na barze wejscia), SL -> entry."""
    # BE level = 140 + 0.4*60 = 164; entry 170, TP 155, SL 200
    bars = _prefix() + [mk(11, 160, 171, 158, 168),     # entry; low 158 <= 164, ale entry bar
                        mk(12, 168, 170.5, 163, 166),   # gdyby BE zbrojone: stop 170; zbroi teraz
                        mk(13, 169, 171, 166, 168)]     # stop na BE (high >= 170)
    trades = _bt(bars, BE_AT_FIB=0.4).run()
    assert len(trades) == 1
    t = trades[0]
    assert t.be_moved and t.result == "sl"
    assert t.exit_ts == bars[13].ts        # NIE bar 12 -> entry bar nie zbroil BE
    assert abs(t.sl - 170.0) < 1e-9 and abs(t.exit - 170.0) < 1e-9
    assert abs(t.pnl) < 1e-9
    assert abs(t.risk_pt - 30.0) < 1e-9    # risk zamrozony mimo przesuniecia SL


# ---------- BIAS_TFS ----------

def test_bias_tfs_subset_ignores_excluded_tf():
    """Podzbior TF: cena nad EMA15m (blokuje short w 4xTF), ale HTF-only daje short."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168)]
    price = 180.0   # nad ema15[10] (~172.4), pod EMA HTF (~200+)
    assert _bt(bars).bias_all(11, price) is None
    assert _bt(bars, BIAS_TFS=("1h", "4h", "1d")).bias_all(11, price) == "short"


# ---------- struktura biasu: BOS / HH-HL ----------

def test_struct_bos_breaks_high_sets_long():
    """BOS: close powyzej ostatniego swing high -> stan +1; przed zlamaniem 0."""
    piv = 2
    bars = (flat(2) + [mk(2, 100, 110, 99, 101)]      # pivot high 110 (cand i=2)
            + flat(2, start=3)                         # i=4 potwierdza ph1=110
            + [mk(5, 100, 115, 100, 112)])             # close 112 > 110 -> bos +1
    st = engine.compute_struct_states(bars, piv)
    assert st[4][0] == 0      # ph potwierdzony, ale jeszcze nie zlamany
    assert st[5][0] == 1


def test_struct_bos_breaks_low_sets_short():
    """BOS: close ponizej ostatniego swing low -> stan -1."""
    piv = 2
    bars = (flat(2) + [mk(2, 100, 101, 90, 100)]      # pivot low 90 (cand i=2)
            + flat(2, start=3)                         # i=4 potwierdza pl1=90
            + [mk(5, 100, 101, 85, 88)])               # close 88 < 90 -> bos -1
    st = engine.compute_struct_states(bars, piv)
    assert st[4][0] == 0
    assert st[5][0] == -1


def test_struct_hhhl_higher_high_and_higher_low():
    """HH/HL: 2 rosnace swing high I 2 rosnace swing low -> +1; flat -> 0."""
    piv = 1
    bars = [mk(0, 91, 92, 91, 91),
            mk(1, 92, 93, 90, 92),     # pivot low 90  (conf i=2)
            mk(2, 96, 100, 96, 99),    # pivot high 100 (conf i=3)
            mk(3, 98, 99, 95, 96),     # pivot low 95   (conf i=4)
            mk(4, 100, 106, 98, 104),  # pivot high 106 (conf i=5)
            mk(5, 104, 105, 100, 102)]
    st = engine.compute_struct_states(bars, piv)
    assert st[5][1] == 1               # HH(106>100) + HL(95>90)
    assert engine.compute_struct_states(flat(20), piv)[-1][1] == 0   # brak pivotow -> neutral


def test_bias_all_structure_bos_single_tf():
    """Sciezka strukturalna w bias_all: BOS na 15m -> long; przed zlamaniem -> None (neutral)."""
    bars = (flat(2) + [mk(2, 100, 110, 99, 101)] + flat(2, start=3)
            + [mk(5, 100, 115, 100, 112)] + flat(4, start=6))
    bt = _bt(bars, BIAS_METHOD="BOS", STRUCT_PIVOT_LEN=2, BIAS_TFS=("15m",))
    assert bt.bias_all(6, 0.0) == "long"    # czyta struct15[5] = +1 (price ignorowane)
    assert bt.bias_all(5, 0.0) is None      # czyta struct15[4] = 0 -> neutral blokuje


# ---------- displacement-gated BOS ----------

def test_struct_displacement_gate_requires_momentum():
    """disp_mult>0: slabe zlamanie (maly range bara) nie flipuje BOS; mocne przechodzi."""
    piv = 2
    weak = (flat(2) + [mk(2, 100, 110, 99, 101)] + flat(2, start=3)
            + [mk(5, 110, 110.6, 109.5, 110.4)])   # close 110.4 > swing high 110, ale range 1.1
    assert engine.compute_struct_states(weak, piv)[5][0] == 1               # bez gate: flip
    assert engine.compute_struct_states(weak, piv, disp_mult=1.5, disp_len=2)[5][0] == 0  # z gate: blok
    strong = (flat(2) + [mk(2, 100, 110, 99, 101)] + flat(2, start=3)
              + [mk(5, 100, 120, 100, 118)])       # range 20 >> ATR -> przechodzi
    assert engine.compute_struct_states(strong, piv, disp_mult=1.5, disp_len=2)[5][0] == 1


# ---------- HtfPrior (PDH/PDL) ----------

def test_htf_prior_previous_day_high_low():
    """HtfPrior.at zwraca H/L bara HTF POPRZEDZAJACEGO ten z t (parytet [1]+lookahead)."""
    d1 = [Bar(TS0 + i * 86400, 100 + i, 110 + i, 90 + i, 100 + i, 0) for i in range(5)]
    hp = engine.HtfPrior(d1)
    hi, lo = hp.at(TS0 + 3 * 86400 + 3600)   # t w dniu 3 -> zwraca dzien 2
    assert hi == d1[2].h and lo == d1[2].l


# ---------- filtr sesji ----------

def test_session_filter_blocks_out_of_session_entry():
    """SESSION_FILTER: wejscie poza dozwolona sesja odrzucone (rej_session), bez filtra przechodzi."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    assert len(_bt(bars).run()) == 1                       # _bt: SESSION_FILTER=False
    bt = _bt(bars, SESSION_FILTER=True, TRADE_SESSIONS=())  # pusta lista = nic nie wpuszczamy
    assert bt.run() == []
    assert bt.funnel["rej_session"] >= 1


# ---------- wyjscia plynnosciowe ----------

def _bt_liq(bars, d1, **over):
    base = dict(PIVOT_LEN=2, EMA_LEN=10, ENTRY_FIB=0.5, BIAS_METHOD="EMA20",
                SESSION_FILTER=False, EXIT_MODE="liquidity", SL_BUFFER_TICKS=4,
                TP_MIN_R=1.0, TP_MAX_R=4.0, SLIPPAGE_TICKS_ENTRY=0, COMMISSION_RT=0.0)
    base.update(over)
    h1, _ = _htf_falling()
    return Backtester(_cfg(**base), bars, h1, h1, d1)


def test_liquidity_exit_sl_behind_swing_tp_at_pdl():
    """short: SL = swing high + bufor; TP = PDL (najblizszy wazny cel o R w [1,4])."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168)]
    d1 = [Bar(TS0 - 2 * 86400, 200, 210, 150, 160, 0),
          Bar(TS0 - 86400, 160, 175, 150, 168, 0)]   # PDL = 150
    bt = _bt_liq(bars, d1)
    sl, tp = bt._exit_levels(11, "short", 200.0, 140.0, 190.0)
    assert abs(sl - (200 + 4 * 0.25)) < 1e-9          # 201
    assert abs(tp - 150.0) < 1e-9                     # PDL, R=(190-150)/11=3.6 in [1,4]


def test_liquidity_exit_falls_back_to_fib_when_no_target():
    """Brak celu o R>=TP_MIN_R -> fallback na fib TP (TP_FIB nogi)."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168)]
    d1 = [Bar(TS0 - 2 * 86400, 300, 310, 290, 300, 0),
          Bar(TS0 - 86400, 300, 310, 290, 300, 0)]   # PDL=290 powyzej fillu -> bezuzyteczny dla short
    bt = _bt_liq(bars, d1, TP_FIB=0.25, TP_MIN_R=5.0)  # wysoki prog -> nic nie przejdzie
    sl, tp = bt._exit_levels(11, "short", 200.0, 140.0, 190.0)
    assert abs(tp - (140 + 0.25 * 60)) < 1e-9         # fib TP = 155


# ---------- position sizing wg ryzyka ----------

def test_position_size_risk_based():
    """contracts = round(RISK_PER_TRADE_USD / (risk_pt*POINT_VALUE)), clamp i skip > MAX_RISK_USD."""
    bt = _bt(_prefix(), SIZING_MODE="risk", RISK_PER_TRADE_USD=100.0, MAX_CONTRACTS=10, MAX_RISK_USD=200.0)
    assert bt._position_size(30.0) == 2       # ryzyko $60 -> 100/60≈1.67 -> 2
    assert bt._position_size(5.0) == 10       # ryzyko $10 -> 10, clamp MAX_CONTRACTS
    assert bt._position_size(120.0) is None   # ryzyko $240 > $200 -> skip
    assert _bt(_prefix(), SIZING_MODE="fixed", CONTRACTS=1)._position_size(30.0) == 1


def test_sizing_scales_pnl_and_skips_fat_stop():
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    t = _bt(bars, SIZING_MODE="risk", RISK_PER_TRADE_USD=100.0).run()[0]
    assert t.contracts == 2                                  # risk_pt 30 -> 2 kontrakty
    assert abs(t.pnl - (170 - 155) * 2.0 * 2) < 1e-9         # pnl x2
    # MAX_RISK_USD niski -> wejscie z risk_pt 30 ($60) odrzucone (fat-stop guard)
    bt = _bt(bars, SIZING_MODE="risk", MAX_RISK_USD=40.0)
    assert bt.run() == []
    assert bt.funnel["rej_maxrisk"] >= 1


# ---------- wyjscie czasowe ----------

def test_max_hold_bars_forces_time_exit():
    """MAX_HOLD_BARS: po N domknietych barach pozycja zamykana po close (result 'time')."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168),   # entry 170 (FVG)
                        mk(12, 168, 170, 166, 167),   # ani TP(155) ani SL(200)
                        mk(13, 167, 169, 165, 166)]
    t = _bt(bars, MAX_HOLD_BARS=1).run()[0]
    assert t.result == "time"
    assert t.exit_ts == bars[12].ts and abs(t.exit - 167.0) < 1e-9   # close bara 12


# ---------- filtr sweep (confluence) ----------

def test_swept_and_reclaimed_long():
    """sweep+reclaim: w oknie cena zeszla pod swing low i close wrocil powyzej."""
    bars = [mk(i, 100, 101, 99, 100) for i in range(20)]
    bars[15] = mk(15, 100, 101, 90, 100)   # zmiecenie: low 90 < swing low 95
    bt = _bt(bars)
    bt.legs = [engine.LegState(sw_l=95.0, sw_h=200.0, run_min=90.0, run_max=101.0) for _ in bars]
    bt.pdhl = type("P", (), {"at": lambda self, t: (None, None)})()
    assert bt.swept_and_reclaimed(17, "long") is True    # okno [5:17] zawiera bar15, close>95
    assert bt.swept_and_reclaimed(14, "long") is False   # okno [2:14] bez zmiecenia


# ---------- OTE jako strefa (scale-in) + instrument ----------

def _zone_cfg(**over):
    base = dict(PIVOT_LEN=2, EMA_LEN=10, ENTRY_FIB=0.5, BIAS_METHOD="EMA20", SESSION_FILTER=False,
                EXIT_MODE="fib", BIAS_TFS=("15m", "1h", "4h", "1d"), SLIPPAGE_TICKS_ENTRY=0,
                COMMISSION_RT=0.0)
    base.update(over)
    return _cfg(**base)


def test_entry_zone_single_matches_direct():
    """ENTRY_FIBS z 1 poziomem = identyczne z bezposrednim Backtesterem (brak regresji)."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    h1, d1 = _htf_falling()
    cfg = _zone_cfg(ENTRY_FIBS=(0.5,), SIZING_MODE="fixed")
    direct = Backtester(cfg, bars, h1, h1, d1).run()
    zoned, _f, _s, _bt = engine.run_entry_zone(cfg, bars, h1, h1, d1)
    assert len(zoned) == len(direct) == 1
    assert abs(zoned[0].pnl - direct[0].pnl) < 1e-9


def test_entry_zone_multi_splits_risk_budget():
    """2 transze -> 2 sub-trade'y, kazdy z 1/2 budzetu ryzyka."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    h1, d1 = _htf_falling()
    cfg = _zone_cfg(ENTRY_FIBS=(0.5, 0.5), SIZING_MODE="risk", RISK_PER_TRADE_USD=100.0)
    tr, _f, _s, _bt = engine.run_entry_zone(cfg, bars, h1, h1, d1)
    assert len(tr) == 2                       # 2 identyczne transze fillują tę samą nogę
    assert all(t.contracts == 1 for t in tr)  # budżet $50/transza, risk_pt 30 ($60) -> 1 kontrakt


def test_instrument_point_value_scales_pnl():
    """POINT_VALUE (parametr instrumentu) skaluje pnl: MES $5/pkt = 2.5x MNQ $2/pkt."""
    bars = _prefix() + [mk(11, 160, 171, 158, 168), mk(12, 168, 169, 154, 156)]
    t_mnq = _bt(bars, POINT_VALUE=2.0).run()[0]
    t_mes = _bt(bars, POINT_VALUE=5.0).run()[0]
    assert abs(t_mes.pnl / t_mnq.pnl - 2.5) < 1e-9
