"""Silnik backtestu strategii "Fib OTE 0.79 + bias 4xTF" na MNQ.

Port 1:1 logiki z indykatora Pine "ICT Setup — NQ All-In-One"
(pine/ict_setup_nq_all_in_one.pine):
- bias per TF: cena vs EMA20 ostatniego ZAMKNIETEGO bara danego TF (semantyka [1]+lookahead),
- noga Fib 15m: f_fib_state (pivoty 5/5, running extremes, stan z zamknietych barow),
- FVG 15m ze stanami active/mitigated/inverted i min. rozmiarem,
- NWOG (gap pt 17:00 -> nd 18:00 ET) z wypelnieniem przy powrocie do prior close,
- key opens 00:00/10:00/18:00 ET.

Symulacja na barach 15m, rozstrzygniecia konserwatywne (BOTH_HIT_RULE).
"""
from __future__ import annotations

import csv
import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_SESSION_SHIFT = timedelta(hours=18)   # sesja CME "D" startuje 18:00 ET


@dataclass
class Bar:
    ts: int
    o: float
    h: float
    l: float
    c: float
    v: float


def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            bars.append(Bar(int(row["time"]), float(row["open"]), float(row["high"]),
                            float(row["low"]), float(row["close"]), float(row["volume"])))
    bars.sort(key=lambda b: b.ts)
    # dedupe po ts (nakladajace sie eksporty)
    out: list[Bar] = []
    for b in bars:
        if out and out[-1].ts == b.ts:
            out[-1] = b
        else:
            out.append(b)
    return out


def ema_series(closes: list[float], n: int) -> list[float | None]:
    """EMA jak ta.ema: alpha=2/(n+1); seed = SMA(n) na barze n-1; None w okresie rozbiegu."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) < n:
        return out
    alpha = 2.0 / (n + 1)
    seed = sum(closes[:n]) / n
    out[n - 1] = seed
    for i in range(n, len(closes)):
        out[i] = alpha * closes[i] + (1 - alpha) * out[i - 1]
    return out


def atr_series(bars: list[Bar], n: int) -> list[float | None]:
    """ATR jak Pine ta.atr (RMA/Wilder na true range); None w okresie rozbiegu."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n + 1:
        return out
    tr = [0.0] * len(bars)
    for i in range(1, len(bars)):
        pc = bars[i - 1].c
        tr[i] = max(bars[i].h - bars[i].l, abs(bars[i].h - pc), abs(bars[i].l - pc))
    seed = sum(tr[1:n + 1]) / n          # SMA pierwszych n TR (TR[0] pomijany)
    out[n] = seed
    for i in range(n + 1, len(bars)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


class HtfEma:
    """EMA20 wyzszego TF z semantyka Pine [1]+lookahead_on:
    dla chwili t -> EMA bara HTF POPRZEDZAJACEGO ten, w ktorym lezy t."""

    def __init__(self, bars: list[Bar], n: int):
        self.ts = [b.ts for b in bars]
        self.ema = ema_series([b.c for b in bars], n)

    def at(self, t: int) -> float | None:
        k = bisect_right(self.ts, t) - 1   # bar HTF zawierajacy t
        if k < 1:
            return None
        return self.ema[k - 1]


@dataclass
class LegState:
    """Stan nogi Fib PO zamknieciu bara i (odpowiednik wartosci 'biezacych' w Pine;
    sygnaly na barze i czytaja stan z bara i-1 = eksport [1])."""
    sw_h: float | None = None
    sw_ht: int | None = None
    sw_l: float | None = None
    sw_lt: int | None = None
    run_max: float | None = None
    run_min: float | None = None


def compute_leg_states(bars: list[Bar], piv_len: int) -> list[LegState]:
    """Port f_fib_state. Pivot 5/5: srodek STRICTLY wyzszy/nizszy od pozostalych barow okna
    (remisy -> brak pivota, jak ta.pivothigh/low)."""
    n = len(bars)
    states: list[LegState] = []
    st = LegState()
    for i in range(n):
        st = LegState(**vars(st))  # kopia poprzedniego stanu
        if i >= 2 * piv_len:
            j = i - piv_len  # kandydat na pivot
            win = bars[i - 2 * piv_len:i + 1]
            ph = all(bars[j].h > b.h for b in win if b is not bars[j])
            pl = all(bars[j].l < b.l for b in win if b is not bars[j])
            if ph:
                st.sw_h = bars[j].h
                st.sw_ht = bars[j].ts
                st.run_min = min(b.l for b in bars[i - piv_len:i + 1])  # ll = lowest(len+1)
            if pl:
                st.sw_l = bars[j].l
                st.sw_lt = bars[j].ts
                st.run_max = max(b.h for b in bars[i - piv_len:i + 1])  # hh = highest(len+1)
        st.run_max = bars[i].h if st.run_max is None else max(st.run_max, bars[i].h)
        st.run_min = bars[i].l if st.run_min is None else min(st.run_min, bars[i].l)
        states.append(st)
    return states


def compute_struct_states(bars: list[Bar], piv_len: int,
                          disp_mult: float = 0.0, disp_len: int = 14) -> list[tuple[int, int]]:
    """Port f_struct_bias z Pine. Zwraca per-bar (bos, hhhl), kazdy w {-1,0,1} = stan PO
    zamknieciu bara i (konsument czyta [i-1] / [k-1] = semantyka [1]+lookahead).
    Pivot N/N jak compute_leg_states (srodek STRICTLY ekstremalny; remisy -> brak pivota).
    - bos:  stanowy. close > ostatni swing high -> +1; close < ostatni swing low -> -1; inaczej trzyma.
    - hhhl: HH+HL (ph1>ph2 i pl1>pl2) -> +1; LH+LL -> -1; inaczej 0 (NEUTRAL).
    disp_mult > 0: displacement-gate — flip BOS tylko gdy range bara >= disp_mult*ATR(disp_len)."""
    n = len(bars)
    atr = atr_series(bars, disp_len) if disp_mult > 0 else None
    out: list[tuple[int, int]] = []
    ph1 = ph2 = pl1 = pl2 = None  # 2 ostatnie potwierdzone swing high/low
    bos = 0
    for i in range(n):
        if i >= 2 * piv_len:
            j = i - piv_len  # kandydat na pivot (srodek okna)
            win = bars[i - 2 * piv_len:i + 1]
            is_ph = all(bars[j].h > b.h for b in win if b is not bars[j])
            is_pl = all(bars[j].l < b.l for b in win if b is not bars[j])
            if is_ph:
                ph2, ph1 = ph1, bars[j].h
            if is_pl:
                pl2, pl1 = pl1, bars[j].l
        c = bars[i].c
        disp_ok = (disp_mult <= 0 or
                   (atr[i] is not None and (bars[i].h - bars[i].l) >= disp_mult * atr[i]))
        if ph1 is not None and c > ph1 and disp_ok:
            bos = 1
        if pl1 is not None and c < pl1 and disp_ok:
            bos = -1
        if ph2 is not None and pl2 is not None and ph1 > ph2 and pl1 > pl2:
            hhhl = 1
        elif ph2 is not None and pl2 is not None and ph1 < ph2 and pl1 < pl2:
            hhhl = -1
        else:
            hhhl = 0
        out.append((bos, hhhl))
    return out


class HtfStruct:
    """Stan struktury (bos, hhhl) wyzszego TF z semantyka Pine [1]+lookahead_on:
    dla chwili t -> stan bara HTF POPRZEDZAJACEGO ten, w ktorym lezy t."""

    def __init__(self, bars: list[Bar], piv_len: int,
                 disp_mult: float = 0.0, disp_len: int = 14):
        self.ts = [b.ts for b in bars]
        self.states = compute_struct_states(bars, piv_len, disp_mult, disp_len)

    def at(self, t: int) -> tuple[int, int] | None:
        k = bisect_right(self.ts, t) - 1   # bar HTF zawierajacy t
        if k < 1:
            return None
        return self.states[k - 1]


class HtfPrior:
    """High/low POPRZEDNIEGO zamknietego bara HTF (parytet Pine
    request.security("D",[high[1],low[1]],lookahead_on)) — np. PDH/PDL z d1."""

    def __init__(self, bars: list[Bar]):
        self.ts = [b.ts for b in bars]
        self.hi = [b.h for b in bars]
        self.lo = [b.l for b in bars]

    def at(self, t: int) -> tuple[float | None, float | None]:
        k = bisect_right(self.ts, t) - 1
        if k < 1:
            return None, None
        return self.hi[k - 1], self.lo[k - 1]


@dataclass
class Fvg:
    bull: bool
    top: float
    bot: float
    created: int            # indeks bara 15m, na ktorym powstal
    mitigated: int | None = None
    inverted: int | None = None


def compute_fvgs(bars: list[Bar], min_pt: float) -> list[Fvg]:
    """FVG 15m jak w Pine: bull gdy high[2] < low[0] (>= min_pt); touch -> mitigated,
    close-through -> inverted. Przejscia oceniane na barach PO created (bar_index > created)."""
    fvgs: list[Fvg] = []
    for i in range(2, len(bars)):
        if bars[i].l - bars[i - 2].h >= min_pt:
            fvgs.append(Fvg(True, bars[i].l, bars[i - 2].h, i))
        if bars[i - 2].l - bars[i].h >= min_pt:
            fvgs.append(Fvg(False, bars[i - 2].l, bars[i].h, i))
    for g in fvgs:
        for i in range(g.created + 1, len(bars)):
            b = bars[i]
            inverted = b.c < g.bot if g.bull else b.c > g.top
            touched = b.l <= g.top if g.bull else b.h >= g.bot
            if inverted:
                g.inverted = i
                break
            if touched and g.mitigated is None:
                g.mitigated = i
    return fvgs


@dataclass
class Nwog:
    top: float
    bot: float
    prior_close: float       # dalsza krawedz (level wypelnienia)
    gap_up: bool
    created: int
    filled: int | None = None


def _et(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=ET)


def _new_session_day(prev: Bar, cur: Bar) -> bool:
    """Zmiana dnia sesyjnego CME (dzien 'D' w TV zaczyna sie 18:00 ET)."""
    return (_et(cur.ts) - _SESSION_SHIFT).date() != (_et(prev.ts) - _SESSION_SHIFT).date()


def compute_nwogs(bars: list[Bar]) -> list[Nwog]:
    """NWOG: nowy dzien sesyjny (pierwszy bar >= 18:00 ET po przerwie) w NIEDZIELE;
    gap = close[1] (pt 17:00) -> open; filled = powrot do prior close."""
    nwogs: list[Nwog] = []
    for i in range(1, len(bars)):
        if not _new_session_day(bars[i - 1], bars[i]):
            continue
        if _et(bars[i].ts).weekday() != 6:   # niedziela
            continue
        gap_a = bars[i - 1].c
        gap_b = bars[i].o
        if abs(gap_b - gap_a) < 0.5:   # syminfo.mintick*2
            continue
        g = Nwog(max(gap_a, gap_b), min(gap_a, gap_b), gap_a, gap_b > gap_a, i)
        for k in range(i + 1, len(bars)):
            filled = bars[k].l <= gap_a if g.gap_up else bars[k].h >= gap_a
            if filled:
                g.filled = k
                break
        nwogs.append(g)
    return nwogs


@dataclass
class KeyOpen:
    ts: int
    price: float
    label: str


def compute_key_opens(bars: list[Bar], opens_et: tuple[str, ...]) -> list[KeyOpen]:
    out = []
    wanted = set(opens_et)
    for b in bars:
        hhmm = _et(b.ts).strftime("%H:%M")
        if hhmm in wanted:
            out.append(KeyOpen(b.ts, b.o, hhmm))
    return out


def killzone(ts: int) -> str:
    d = _et(ts)
    hm = d.hour * 60 + d.minute
    wd = d.weekday()
    if wd <= 4 and 2 * 60 <= hm < 5 * 60:
        return "London"
    if wd <= 4 and 8 * 60 + 30 <= hm < 11 * 60:
        return "NY AM"
    if wd <= 4 and 11 * 60 + 30 <= hm < 13 * 60:
        return "NY Lunch"
    if wd <= 4 and 13 * 60 + 30 <= hm < 16 * 60:
        return "NY PM"
    if 20 * 60 <= hm:
        return "Asian"
    return "—"


@dataclass
class Trade:
    side: str
    entry_ts: int
    entry: float
    sl: float
    tp: float
    exit_ts: int = 0
    exit: float = 0.0
    result: str = ""          # "tp" | "sl"
    pnl: float = 0.0
    r: float = 0.0
    filter: str = ""          # "fvg" | "nwog" | "key_open" | "none" (shadow)
    leg_h: float = 0.0
    leg_l: float = 0.0
    kz: str = ""
    mae_pt: float = 0.0       # max adverse excursion w pkt od entry (pelny zakres h/l barow)
    mfe_pt: float = 0.0       # max favorable excursion w pkt od entry
    post_tp_bars: int | None = None  # po SL: za ile barow cena dotknela oryginalnego TP (0 = bar SL)
    risk_pt: float = 0.0      # |entry - SL| zamrozone przy wejsciu (BE przesuwa sl, nie risk)
    fill_at_open: bool = False  # fill na open bara -> pozycja trzymana od poczatku bara
    be_moved: bool = False    # SL przesuniety na entry po osiagnieciu BE_AT_FIB
    contracts: int = 1        # wielkosc pozycji (sizing wg ryzyka)
    bars_held: int = 0        # liczba domknietych barow trzymania (dla MAX_HOLD_BARS)

    def __post_init__(self):
        if self.risk_pt == 0.0:
            self.risk_pt = abs(self.entry - self.sl)


class Backtester:
    def __init__(self, cfg, m15: list[Bar], h1: list[Bar], h4: list[Bar], d1: list[Bar]):
        self.cfg = cfg
        self.m15 = m15
        self.ema15 = ema_series([b.c for b in m15], cfg.EMA_LEN)
        self.h1 = HtfEma(h1, cfg.EMA_LEN)
        self.h4 = HtfEma(h4, cfg.EMA_LEN)
        self.d1 = HtfEma(d1, cfg.EMA_LEN)
        _spl = getattr(cfg, "STRUCT_PIVOT_LEN", cfg.PIVOT_LEN)
        _dm = getattr(cfg, "DISP_ATR_MULT", 1.5) if getattr(cfg, "BOS_DISPLACEMENT", False) else 0.0
        _dl = getattr(cfg, "DISP_ATR_LEN", 14)
        self.struct15 = compute_struct_states(m15, _spl, _dm, _dl)
        self.hs1 = HtfStruct(h1, _spl, _dm, _dl)
        self.hs4 = HtfStruct(h4, _spl, _dm, _dl)
        self.hsd = HtfStruct(d1, _spl, _dm, _dl)
        self.pdhl = HtfPrior(d1)   # PDH/PDL = high/low poprzedniego bara dziennego
        self.legs = compute_leg_states(m15, cfg.PIVOT_LEN)
        self.fvgs = compute_fvgs(m15, cfg.FVG_MIN_PT)
        self.nwogs = compute_nwogs(m15)
        self.key_opens = compute_key_opens(m15, cfg.KEY_OPENS_ET)
        self._ko_ts = [k.ts for k in self.key_opens]
        self.shadow_trades: list[Trade] = []
        # pierwsze bary po weekendzie (niedzielne otwarcie 18:00 ET)
        self._weekend_open_idx = {i for i in range(1, len(m15))
                                  if _new_session_day(m15[i - 1], m15[i])
                                  and _et(m15[i].ts).weekday() == 6}

    # --- bias ---
    def bias_all(self, i: int, price: float) -> str | None:
        """Zwraca 'long'/'short' gdy biasy wszystkich TF z BIAS_TFS zgodne na barze i.
        BIAS_METHOD: 'BOS'/'HH/HL' (struktura, price ignorowane) lub 'EMA20' (cena vs EMA20)."""
        if i < 1:
            return None
        t = self.m15[i].ts
        tfs = getattr(self.cfg, "BIAS_TFS", ("15m", "1h", "4h", "1d"))
        method = getattr(self.cfg, "BIAS_METHOD", "BOS")

        if method == "EMA20":
            emas = {"15m": self.ema15[i - 1], "1h": self.h1.at(t),
                    "4h": self.h4.at(t), "1d": self.d1.at(t)}
            sel = [emas[tf] for tf in tfs]
            if not sel or None in sel:
                return None
            if all(price > e for e in sel):
                return "long"
            if all(price < e for e in sel):
                return "short"
            return None

        # struktura (BOS / HH/HL): bias = stan zamknietych barow, niezalezny od price
        idx = 0 if method == "BOS" else 1
        s15 = self.struct15[i - 1] if i - 1 < len(self.struct15) else None
        states = {"15m": s15, "1h": self.hs1.at(t), "4h": self.hs4.at(t), "1d": self.hsd.at(t)}
        vals: list[int] = []
        for tf in tfs:
            st = states[tf]
            if st is None:
                return None
            vals.append(st[idx])
        if not vals:
            return None
        if all(v > 0 for v in vals):
            return "long"
        if all(v < 0 for v in vals):
            return "short"
        return None   # neutral na ktorymkolwiek TF (HH/HL) lub mieszane -> brak wejscia

    # --- filtry ---
    def in_aligned_fvg(self, i: int, price: float, side: str) -> bool:
        want_bull = side == "long"
        # indykator trzyma tylko FVG_KEEP ostatnio utworzonych boxow (obu kierunkow)
        kept = [g for g in self.fvgs if g.created < i][-self.cfg.FVG_KEEP:]
        live = [g for g in kept
                if g.bull == want_bull and (g.inverted is None or g.inverted >= i)]
        return any(g.bot <= price <= g.top for g in live)

    def in_nwog(self, i: int, price: float) -> bool:
        live = [g for g in self.nwogs if g.created < i and (g.filled is None or g.filled >= i)]
        live = live[-self.cfg.NWOG_KEEP:]
        return any(g.bot <= price <= g.top for g in live)

    def near_key_open(self, i: int, price: float) -> bool:
        t = self.m15[i].ts
        k = bisect_right(self._ko_ts, t) - 1
        if k < 0:
            return False
        ko = self.key_opens[k]
        if t - ko.ts >= self.cfg.KEY_OPEN_WINDOW_MIN * 60:
            return False
        return abs(price - ko.price) <= self.cfg.KEY_OPEN_MAX_TICKS * self.cfg.TICK

    def swept_and_reclaimed(self, i: int, side: str) -> bool:
        """Confluence ICT: w ostatnich SWEEP_LOOKBACK barach cena zmiotla poziom plynnosci
        (PDL/sesyjny swing low dla long; PDH/swing high dla short) i go ODZYSKALA (close z powrotem
        po wlasciwej stronie). Reuse self.pdhl + self.legs."""
        K = getattr(self.cfg, "SWEEP_LOOKBACK", 12)
        window = self.m15[max(0, i - K):i]   # bary przed wejsciem
        if not window:
            return False
        pdh, pdl = self.pdhl.at(self.m15[i].ts)
        st = self.legs[i - 1]
        c = self.m15[i - 1].c
        if side == "long":
            for lv in (pdl, st.sw_l):
                if lv is not None and c > lv and any(bb.l < lv for bb in window):
                    return True
        else:
            for lv in (pdh, st.sw_h):
                if lv is not None and c < lv and any(bb.h > lv for bb in window):
                    return True
        return False

    def entry_filter(self, i: int, price: float, side: str) -> str | None:
        mode = getattr(self.cfg, "ENTRY_FILTER_MODE", "legacy")
        if mode == "none":
            return "all"
        if mode == "sweep":
            return "sweep" if self.swept_and_reclaimed(i, side) else None
        # "legacy" / "loose" (loose = legacy z luzniejszymi progami przez override w sweepie)
        if self.in_aligned_fvg(i, price, side):
            return "fvg"
        if self.in_nwog(i, price):
            return "nwog"
        if self.near_key_open(i, price):
            return "key_open"
        return None

    def _position_size(self, risk_pt: float) -> int | None:
        """Liczba kontraktow wg cfg.SIZING_MODE. None = skip (ryzyko 1 kontraktu > MAX_RISK_USD)."""
        cfg = self.cfg
        if getattr(cfg, "SIZING_MODE", "fixed") != "risk":
            return cfg.CONTRACTS
        risk_usd = risk_pt * cfg.POINT_VALUE
        if risk_usd <= 0:
            return cfg.CONTRACTS
        if risk_usd > getattr(cfg, "MAX_RISK_USD", float("inf")):
            return None
        n = round(getattr(cfg, "RISK_PER_TRADE_USD", 100.0) / risk_usd)
        return max(1, min(getattr(cfg, "MAX_CONTRACTS", 10), n))

    # --- glowna petla ---
    def run(self) -> list[Trade]:
        cfg = self.cfg
        trades: list[Trade] = []
        pos: Trade | None = None
        traded_legs: set[tuple] = set()
        self.shadow_trades = []
        shadow_open: list[Trade] = []
        shadow_legs: set[tuple] = set()
        self.funnel = {"bars": 0, "bias_aligned": 0, "cross": 0,
                       "rej_min_leg": 0, "rej_gap_guard": 0, "rej_maxrisk": 0, "rej_filter": 0,
                       "rej_weekend": 0, "rej_session": 0, "shadow": 0, "entries": 0}

        for i in range(1, len(self.m15)):
            b = self.m15[i]

            # zarzadzanie otwarta pozycja (bary PO wejsciu)
            if pos is not None and b.ts > pos.entry_ts:
                pos = self._manage(pos, b, trades, idx=i)

            # zarzadzanie shadow trades (zawsze; pozycje rownolegle dozwolone,
            # statystyka per-sygnal — nie krzywa kapitalu)
            if shadow_open:
                still_open: list[Trade] = []
                for sp in shadow_open:
                    if b.ts > sp.entry_ts:
                        sp = self._manage(sp, b, self.shadow_trades, idx=i)
                    if sp is not None:
                        still_open.append(sp)
                shadow_open = still_open

            if pos is not None:
                continue

            self.funnel["bars"] += 1
            if getattr(cfg, "SKIP_FIRST_BAR_AFTER_WEEKEND", False) and i in self._weekend_open_idx:
                self.funnel["rej_weekend"] += 1
                continue
            if getattr(cfg, "SESSION_FILTER", False) and \
                    killzone(b.ts) not in getattr(cfg, "TRADE_SESSIONS", ()):
                # poza dozwolona sesja ICT (martwe godziny) — bez wejscia i bez shadow
                self.funnel["rej_session"] += 1
                continue
            st = self.legs[i - 1]   # stan z zamknietego bara [1]

            sides: list[str]
            if cfg.BIAS_AT == "prev_close":
                # robot: bias = odczyt dashboardu na zamknieciu poprzedniego bara,
                # dopiero potem zbrojony limit na 0.79
                d = self.bias_all(i, self.m15[i - 1].c)
                if d is None:
                    continue
                self.funnel["bias_aligned"] += 1
                sides = [d]
            else:
                sides = ["short", "long"]

            for side in sides:
                fill, H, L, leg_key = self._fill_candidate(st, b, side)
                if fill is None or leg_key in traded_legs:
                    continue
                if cfg.BIAS_AT != "prev_close" and self.bias_all(i, fill) != side:
                    continue
                self.funnel["cross"] += 1
                if H - L < getattr(cfg, "MIN_LEG_PT", 0.0):
                    # noga za mala (stop 0.21 nogi = szum 1 bara); noga NIE skonsumowana —
                    # moze urosnac powyzej progu i zagrac pozniej
                    self.funnel["rej_min_leg"] += 1
                    continue
                sl_level, tp_level = self._exit_levels(i, side, H, L, fill)
                beyond_sl = fill >= sl_level if side == "short" else fill <= sl_level
                if getattr(cfg, "GAP_GUARD", True) and beyond_sl:
                    # fill juz na/za stopem (gap przez limit i SL) = martwe wejscie;
                    # odpowiednik anulowania limitu w live bocie — noga skonsumowana,
                    # zeby nie triggerowala co bar
                    self.funnel["rej_gap_guard"] += 1
                    traded_legs.add(leg_key)
                    continue
                contracts = self._position_size(abs(fill - sl_level))
                if contracts is None:
                    # ryzyko 1 kontraktu > MAX_RISK_USD (fat-stop) — pomijamy, noga skonsumowana
                    self.funnel["rej_maxrisk"] += 1
                    traded_legs.add(leg_key)
                    continue
                f = self.entry_filter(i, fill, side)
                if not f:
                    self.funnel["rej_filter"] += 1
                    if leg_key not in shadow_legs:
                        # shadow trade: sygnal odrzucony filtrem, symulowany identycznie
                        shadow_legs.add(leg_key)
                        self.funnel["shadow"] += 1
                        sp = self._make_trade(side, b, fill, sl_level, tp_level, H, L, "none", contracts)
                        sp = self._manage(sp, b, self.shadow_trades, entry_bar=True, idx=i)
                        if sp is not None:
                            shadow_open.append(sp)
                    continue
                pos = self._make_trade(side, b, fill, sl_level, tp_level, H, L, f, contracts)
                traded_legs.add(leg_key)
                self.funnel["entries"] += 1
                pos = self._manage(pos, b, trades, entry_bar=True, idx=i)
                break

        self._post_exit_probe(trades)
        self._post_exit_probe(self.shadow_trades)
        return trades

    def _make_trade(self, side: str, b: Bar, fill: float, sl_level: float,
                    tp_level: float, H: float, L: float, f: str, contracts: int = 1) -> Trade:
        cfg = self.cfg
        slip = cfg.SLIPPAGE_TICKS_ENTRY * cfg.TICK
        entry = fill - slip if side == "short" else fill + slip
        return Trade(side, b.ts, entry, sl=sl_level, tp=tp_level, filter=f,
                     leg_h=H, leg_l=L, kz=killzone(b.ts),
                     fill_at_open=(fill == b.o), contracts=contracts)

    def _post_exit_probe(self, trades: list[Trade]) -> None:
        """Po SL: najmniejsze k (0..POST_EXIT_BARS), po ktorym cena dotknela oryginalnego TP
        (k=0 = bar SL, kandydat na niejednoznacznosc intrabar); None = brak w oknie.
        Diagnostyka "sweep & reverse" pod decyzje o buforze SL."""
        max_k = getattr(self.cfg, "POST_EXIT_BARS", 12)
        ts_list = [b.ts for b in self.m15]
        for t in trades:
            if t.result != "sl":
                continue
            j = bisect_right(ts_list, t.exit_ts) - 1
            for k in range(max_k + 1):
                if j + k >= len(self.m15):
                    break
                bb = self.m15[j + k]
                if (bb.l <= t.tp) if t.side == "short" else (bb.h >= t.tp):
                    t.post_tp_bars = k
                    break

    def _exit_levels(self, i: int, side: str, H: float, L: float, fill: float):
        """Zwraca (sl_level, tp_level) wg cfg.EXIT_MODE.
        "fib": SL_FIB/TP_FIB nogi (dotychczas). "liquidity": SL za chronionym swingiem + bufor,
        TP na najblizszej przeciwnej plynnosci (PDH/PDL / przeciwny kraniec nogi) z clampem R i
        fallbackiem na fib TP, gdy brak celu o R >= TP_MIN_R."""
        cfg = self.cfg
        # poziomy fib (zarazem fallback dla trybu liquidity)
        if side == "short":
            sl_fib = L + cfg.SL_FIB * (H - L)
            tp_fib = L + cfg.TP_FIB * (H - L)
        else:
            sl_fib = H - cfg.SL_FIB * (H - L)
            tp_fib = H - cfg.TP_FIB * (H - L)
        if getattr(cfg, "EXIT_MODE", "fib") != "liquidity":
            return sl_fib, tp_fib

        buf = getattr(cfg, "SL_BUFFER_TICKS", 4) * cfg.TICK
        sl = (H + buf) if side == "short" else (L - buf)   # SL za chronionym swingiem nogi
        risk = abs(fill - sl)
        if risk <= 0:
            return sl, tp_fib
        pdh, pdl = self.pdhl.at(self.m15[i].ts)
        # kandydaci na cel = przeciwna plynnosc w kierunku zysku
        raw = (pdl, L) if side == "short" else (pdh, H)
        better = (lambda lv: lv < fill) if side == "short" else (lambda lv: lv > fill)
        cands = [lv for lv in raw if lv is not None and better(lv)]
        valid = [lv for lv in cands if abs(fill - lv) / risk >= getattr(cfg, "TP_MIN_R", 1.0)]
        if not valid:
            return sl, tp_fib                       # brak sensownego targetu -> fib TP
        tgt = min(valid, key=lambda lv: abs(fill - lv))   # najblizszy = najwyzsze p. trafienia
        maxd = getattr(cfg, "TP_MAX_R", 4.0) * risk
        if abs(fill - tgt) > maxd:                  # clamp dalekich celow
            tgt = (fill - maxd) if side == "short" else (fill + maxd)
        return sl, tgt

    def _fill_candidate(self, st: LegState, b: Bar, side: str):
        """Zwraca (fill, leg_H, leg_L, leg_key) lub (None, ...) gdy brak fillu."""
        cfg = self.cfg
        if None in (st.sw_h, st.sw_l, st.run_min, st.run_max):
            return None, None, None, None
        if side == "short":
            H, L = st.sw_h, st.run_min
            if H <= L:
                return None, None, None, None
            E = L + cfg.ENTRY_FIB * (H - L)
            fill = b.o if b.o >= E else (E if b.h >= E else None)
            return fill, H, L, (st.sw_ht, "short")
        H, L = st.run_max, st.sw_l
        if H <= L:
            return None, None, None, None
        E = H - cfg.ENTRY_FIB * (H - L)
        fill = b.o if b.o <= E else (E if b.l <= E else None)
        return fill, H, L, (st.sw_lt, "long")

    def _trail_sl(self, pos: Trade, idx: int) -> None:
        """Trailing SL do ostatniego przeciwnego swingu (tylko zacisnij; risk_pt zamrozony)."""
        st = self.legs[idx - 1]
        buf = getattr(self.cfg, "SL_BUFFER_TICKS", 4) * self.cfg.TICK
        if pos.side == "short" and st.sw_h is not None and st.sw_h + buf < pos.sl:
            pos.sl = st.sw_h + buf
        elif pos.side == "long" and st.sw_l is not None and st.sw_l - buf > pos.sl:
            pos.sl = st.sw_l - buf

    def _manage(self, pos: Trade, b: Bar, trades: list[Trade],
                entry_bar: bool = False, idx: int | None = None) -> Trade | None:
        cfg = self.cfg
        tick = cfg.TICK
        if not entry_bar:
            pos.bars_held += 1
        if pos.side == "short":
            pos.mae_pt = max(pos.mae_pt, b.h - pos.entry)
            pos.mfe_pt = max(pos.mfe_pt, pos.entry - b.l)
            hit_sl = b.h >= pos.sl
            hit_tp = b.l <= pos.tp
        else:
            pos.mae_pt = max(pos.mae_pt, pos.entry - b.l)
            pos.mfe_pt = max(pos.mfe_pt, b.h - pos.entry)
            hit_sl = b.l <= pos.sl
            hit_tp = b.h >= pos.tp
        if entry_bar:
            mode = getattr(cfg, "ENTRY_BAR_TP", "deny")
            if mode == "deny":
                hit_tp = False   # sekwencja intrabar nieznana -> TP najwczesniej od nastepnego bara
            elif mode == "provable":
                # TP na barze wejscia tylko gdy pozycja od openu bara i SL nietkniety:
                # wynik pewny niezaleznie od sekwencji intrabar
                hit_tp = hit_tp and pos.fill_at_open and not hit_sl
        if hit_sl and hit_tp and cfg.BOTH_HIT_RULE != "sl_first" and not entry_bar:
            hit_sl = False   # tryb optymistyczny (nieuzywany domyslnie)
        if hit_sl:
            slip = cfg.SLIPPAGE_TICKS_STOP * tick
            if pos.side == "short":
                # luka przez stop -> egzekucja po cenie rynkowej (open), nie po cenie SL
                pos.exit = max(pos.sl, b.o) + slip
            else:
                pos.exit = min(pos.sl, b.o) - slip
            pos.result = "sl"
        elif hit_tp:
            # luka przez TP -> limit wypelnia sie korzystniej (na open)
            pos.exit = min(pos.tp, b.o) if pos.side == "short" else max(pos.tp, b.o)
            pos.result = "tp"
        else:
            # trailing SL do struktury (od nastepnego bara — bez niejednoznacznosci intrabar)
            if getattr(cfg, "TRAIL_TO_SWING", False) and idx is not None and not entry_bar:
                self._trail_sl(pos, idx)
            # wymuszone wyjscie: max czas trzymania lub koniec dozwolonej sesji
            mh = getattr(cfg, "MAX_HOLD_BARS", None)
            forced = (not entry_bar) and (
                (mh and pos.bars_held >= mh) or
                (getattr(cfg, "EXIT_ON_SESSION_END", False)
                 and killzone(b.ts) not in getattr(cfg, "TRADE_SESSIONS", ())))
            if forced:
                pos.exit = b.c          # wyjscie po cenie zamkniecia bara
                pos.result = "time"
            else:
                be = getattr(cfg, "BE_AT_FIB", None)
                if be is not None and not entry_bar and not pos.be_moved:
                    # break-even: domkniety bar osiagnal poziom nogi -> SL na entry od kolejnego
                    # bara (bez niejednoznacznosci intrabar); R nadal liczone z risk_pt
                    if pos.side == "short":
                        trig = b.l <= pos.leg_l + be * (pos.leg_h - pos.leg_l)
                    else:
                        trig = b.h >= pos.leg_h - be * (pos.leg_h - pos.leg_l)
                    if trig:
                        pos.sl = pos.entry
                        pos.be_moved = True
                return pos
        pos.exit_ts = b.ts
        sign = 1 if pos.side == "long" else -1
        pos.pnl = (sign * (pos.exit - pos.entry) * cfg.POINT_VALUE * pos.contracts
                   - cfg.COMMISSION_RT * pos.contracts)
        risk = pos.risk_pt * cfg.POINT_VALUE * pos.contracts
        pos.r = pos.pnl / risk if risk > 0 else 0.0
        trades.append(pos)
        return None


# ---------- konfiguracja / statystyki / wyniki ----------

def make_config(base, overrides: dict | None = None):
    """Kopia konfiguracji (modul lub klasa) jako klasa z nadpisanymi parametrami."""
    class Cfg:
        pass
    for k in dir(base):
        if k.isupper():
            setattr(Cfg, k, getattr(base, k))
    for k, v in (overrides or {}).items():
        setattr(Cfg, k, v)
    return Cfg


def run_entry_zone(cfg, m15, h1, h4, d1):
    """OTE jako STREFA (scale-in). ENTRY_FIBS z >1 poziomem -> uruchom silnik raz na transze
    (ENTRY_FIB=poziom, budzet ryzyka RISK_PER_TRADE_USD/N) i zagreguj trade'y/funnel/shadow —
    dywersyfikacja wejsc po strefie OTE, mniej zalezna od pojedynczego piku. (0.79,) = jak dotad.
    Zwraca (trades, funnel, shadow_trades, bt) — bt do summarize (struktura/cfg)."""
    fibs = tuple(getattr(cfg, "ENTRY_FIBS", None) or (getattr(cfg, "ENTRY_FIB", 0.79),))
    if len(fibs) == 1:
        bt = Backtester(make_config(cfg, {"ENTRY_FIB": fibs[0]}), m15, h1, h4, d1)
        tr = bt.run()
        return tr, bt.funnel, bt.shadow_trades, bt
    n = len(fibs)
    base_risk = getattr(cfg, "RISK_PER_TRADE_USD", 100.0)
    trades: list[Trade] = []
    shadow: list[Trade] = []
    funnel: dict = {}
    last = None
    for fb in fibs:
        sub = make_config(cfg, {"ENTRY_FIB": fb, "ENTRY_FIBS": (fb,),
                                "RISK_PER_TRADE_USD": base_risk / n})
        bt = Backtester(sub, m15, h1, h4, d1)
        trades += bt.run()
        shadow += bt.shadow_trades
        for k, v in bt.funnel.items():
            funnel[k] = funnel.get(k, 0) + v
        last = bt
    trades.sort(key=lambda t: t.entry_ts)
    shadow.sort(key=lambda t: t.entry_ts)
    last.cfg = cfg          # downstream (summarize) widzi oryginalny cfg, nie sub-transzowy
    last.funnel = funnel
    last.shadow_trades = shadow
    return trades, funnel, shadow, last


SEGMENT_GAP_DAYS = 4      # przerwa w 15m dluzsza niz weekend+swieto = dziura w danych
SEGMENT_WARMUP_BARS = 96  # ~1 sesja 15m: na poczatku kawalka pivoty/noga dopiero sie buduja


def split_segments(m15: list[Bar], max_gap_s: int = SEGMENT_GAP_DAYS * 86400) -> list[list[Bar]]:
    """Tnie 15m na ciagle kawalki po dziurach > max_gap_s (np. 12.06-30.06.2026, ktorych TV
    juz nie oddaje). Bez tego noga Fib i pivoty sklejalyby sie przez tygodnie bez swiec."""
    segs: list[list[Bar]] = []
    for b in m15:
        if not segs or b.ts - segs[-1][-1].ts > max_gap_s:
            segs.append([])
        segs[-1].append(b)
    return segs


def run_segmented(cfg, m15, h1, h4, d1, warmup_bars: int = SEGMENT_WARMUP_BARS):
    """run_entry_zone osobno na kazdym ciaglym kawalku 15m (HTF pelne), wyniki sklejone.
    Jeden kawalek = dokladnie run_entry_zone (stare wyniki bez zmian). Przy kilku: na kazdym
    kawalku poza pierwszym wejscia z pierwszych warmup_bars barow sa odrzucane (rozbieg), a
    pozycja otwarta na koncu kawalka nie ma wyniku i odpada jak na koncu danych.
    Zwraca (trades, funnel, shadow, bt) jak run_entry_zone; bt.segments = [(od_ts, do_ts)]."""
    segs = split_segments(m15)
    if len(segs) <= 1:
        tr, fn, sh, bt = run_entry_zone(cfg, m15, h1, h4, d1)
        bt.segments = [(m15[0].ts, m15[-1].ts)] if m15 else []
        return tr, fn, sh, bt
    trades: list[Trade] = []
    shadow: list[Trade] = []
    funnel: dict = {}
    fvgs, nwogs, kos = [], [], []
    bt = None
    for k, seg in enumerate(segs):
        tr, fn, sh, bt = run_entry_zone(cfg, seg, h1, h4, d1)
        lo = seg[min(warmup_bars, len(seg) - 1)].ts if k else seg[0].ts
        trades += [t for t in tr if t.entry_ts >= lo]
        shadow += [t for t in sh if t.entry_ts >= lo]
        for key, v in fn.items():
            funnel[key] = funnel.get(key, 0) + v
        fvgs += bt.fvgs
        nwogs += bt.nwogs
        kos += bt.key_opens
    bt.cfg, bt.funnel, bt.shadow_trades = cfg, funnel, shadow
    bt.fvgs, bt.nwogs, bt.key_opens = fvgs, nwogs, kos
    bt.segments = [(s[0].ts, s[-1].ts) for s in segs]
    return trades, funnel, shadow, bt


def _stats(trades: list[Trade]) -> dict:
    """Wspolny blok statystyk: headline, warianty rozstrzygniecia, shadow, sweep.
    Dla shadow trades max_drawdown jest umowny (PnL per-sygnal, nie portfel)."""
    closed = [t for t in trades if t.result]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    gross_w = sum(t.pnl for t in wins)
    gross_l = -sum(t.pnl for t in losses)
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in closed:
        cum += t.pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(100 * len(wins) / len(closed), 1) if closed else 0,
        "pnl_total": round(sum(t.pnl for t in closed), 2),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
        "expectancy": round(sum(t.pnl for t in closed) / len(closed), 2) if closed else 0,
        "avg_r": round(sum(t.r for t in closed) / len(closed), 3) if closed else 0,
        "max_drawdown": round(max_dd, 2),
    }


def summarize(trades: list[Trade], m15: list[Bar], cfg, funnel: dict | None = None) -> dict:
    closed = [t for t in trades if t.result]
    equity, cum = [], 0.0
    for t in closed:
        cum += t.pnl
        equity.append({"ts": t.exit_ts, "cum": round(cum, 2)})

    def bucket(keyfn):
        out = {}
        for t in closed:
            k = keyfn(t)
            d = out.setdefault(k, {"trades": 0, "wins": 0, "pnl": 0.0})
            d["trades"] += 1
            d["wins"] += 1 if t.pnl > 0 else 0
            d["pnl"] = round(d["pnl"] + t.pnl, 2)
        return out

    return {
        "config": {k: getattr(cfg, k) for k in dir(cfg) if k.isupper()},
        "period": {"from": m15[0].ts, "to": m15[-1].ts, "bars_15m": len(m15)},
        "funnel": funnel or {},
        "stats": _stats(trades),
        "equity": equity,
        "by_filter": bucket(lambda t: t.filter),
        "by_side": bucket(lambda t: t.side),
        "by_killzone": bucket(lambda t: t.kz),
        "by_month": bucket(lambda t: _et(t.entry_ts).strftime("%Y-%m")),
        "r_values": [round(t.r, 3) for t in closed],
        "trades": [vars(t) for t in closed],
    }


def write_outputs(results: dict, out_json: str, out_csv: str) -> None:
    with open(out_json, "w") as f:
        json.dump(results, f, indent=1)
    fields = ["side", "entry_ts", "entry", "sl", "tp", "exit_ts", "exit",
              "result", "pnl", "r", "filter", "leg_h", "leg_l", "kz",
              "mae_pt", "mfe_pt", "post_tp_bars", "risk_pt", "fill_at_open", "be_moved"]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in results["trades"]:
            w.writerow({k: t[k] for k in fields})
