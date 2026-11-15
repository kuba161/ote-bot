"""Parametry strategii "Fib OTE 0.79 + bias 4xTF" — patrz REQUIREMENTS.md."""

# --- poziomy fibo nogi ---
ENTRY_FIB = 0.79          # pojedynczy limit (gdy ENTRY_FIBS ma 1 element); uzywany przez _fill_candidate
# OTE jako STREFA (scale-in): transze wejscia po poziomach Fib, kazda 1/N budzetu ryzyka. Mniej
# zalezne od pojedynczego piku 0.79 (robustness). (0.79,) = pojedyncze wejscie jak dotad.
ENTRY_FIBS = (0.79,)
TP_FIB = 0.25             # take profit na 0.25 nogi
SL_FIB = 1.00             # stop loss na 1.0 nogi (origin swing); >1.0 = bufor za swingiem

# --- bramki strukturalne wejscia ---
MIN_LEG_PT = 0.0          # min rozmiar nogi w pkt (0 = off); stop = (SL_FIB-ENTRY_FIB) nogi,
                          # wiec male nogi daja stopy w szumie 1 bara
GAP_GUARD = True          # nie wchodz, gdy fill jest juz na/za poziomem SL (gap przez limit
                          # i SL, np. niedzielne otwarcie) — odpowiednik anulowania limitu
SKIP_FIRST_BAR_AFTER_WEEKEND = False  # nie otwieraj pozycji na 1. barze po weekendzie

# --- zarzadzanie pozycja ---
BE_AT_FIB = None          # None = off; np. 0.5: gdy domkniety bar osiagnie 0.5 nogi,
                          # SL przesuwa sie na entry (od nastepnego bara)

# --- metoda biasu (parytet z indykatorem Pine: input "Metoda biasu") ---
# "BOS":   stanowy break of structure — bias trzyma kierunek dopoki close nie zlamie
#          ostatniego swing low (->short) / swing high (->long). Zawsze long/short po 1. zlamaniu.
# "HH/HL": porownanie 2 ostatnich swingow — HH+HL=long, LH+LL=short, inaczej NEUTRAL (blokuje wejscie).
# "EMA20": fallback — cena vs EMA20[1] na kazdym TF (stara logika).
BIAS_METHOD = "BOS"
STRUCT_PIVOT_LEN = 5      # pivoty N/N do detekcji swingow biasu (per TF)

# displacement-gated BOS: BOS liczy sie tylko gdy swieca lamiaca ma momentum
# (range >= DISP_ATR_MULT * ATR) — mniej falszywych zlaman. OFF do potwierdzenia w sweepie.
BOS_DISPLACEMENT = False
DISP_ATR_MULT = 1.5
DISP_ATR_LEN = 14

# --- struktura (parytet z indykatorem Pine) ---
PIVOT_LEN = 5             # pivoty 5/5 na 15m (fib_piv_len)
EMA_LEN = 20              # EMA biasu na kazdym TF (sw_ema_len) — uzywane gdy BIAS_METHOD="EMA20"
FVG_MIN_PT = 8.0          # min rozmiar FVG w pkt (fvg_min)
FVG_KEEP = 20             # indykator trzyma max 20 FVG (fvg_max)
NWOG_KEEP = 3             # ostatnie 3 NWOG (og_nwog_max)

# --- filtr key open ---
KEY_OPENS_ET = ("00:00", "10:00", "18:00")
KEY_OPEN_MAX_TICKS = 20   # max odleglosc entry od key open
KEY_OPEN_WINDOW_MIN = 60  # okno waznosci key open w minutach

# --- instrument: MNQ (domyslny) ---
TICK = 0.25
POINT_VALUE = 2.0         # $/pkt
CONTRACTS = 1             # uzywane gdy SIZING_MODE="fixed"

# parametryzacja instrumentow (run_backtest.py --instrument): TICK/POINT_VALUE + prefix plikow danych.
# MES (Micro S&P) = inny indeks niz MNQ -> test generalizacji (czy edge nie jest dopasowany do Nasdaqa).
INSTRUMENTS = {
    "mnq": {"tick": 0.25, "point_value": 2.0, "prefix": "mnq"},
    "mes": {"tick": 0.25, "point_value": 5.0, "prefix": "mes"},
}

# --- position sizing ---
# "fixed": stale CONTRACTS. "risk": liczba kontraktow ze stalego $ ryzyka na trade
# (ryzyko/trade walhalo sie 16x: $21-$329 przy 1 kontrakcie -> normalizacja).
SIZING_MODE = "risk"
RISK_PER_TRADE_USD = 100.0  # docelowe $ ryzyka na trade (risk_pt*POINT_VALUE*contracts ~ to)
MAX_CONTRACTS = 10          # gorny limit wielkosci pozycji
# Zloty srodek (2026-06-26): cap $400 bilansuje bezpieczenstwo i zysk — $200 bylo za ciasne
# (wycinalo dobry fat-stop trade); $400 daje +$2507 przy tym samym maxDD $530 (bije stary fixed $2067).
MAX_RISK_USD = 400.0        # skip wejsc, gdzie nawet 1 kontrakt przekracza budzet (ucina skrajne fat-stopy)

# --- moment oceny biasu ---
# "prev_close": bias 4xTF oceniany na zamknieciu bara poprzedzajacego wejscie
#               (= odczyt dashboardu przed uzbrojeniem limitu na 0.79) — DOMYSLNE
# "entry_price": bias oceniany w cenie wejscia (bardzo restrykcyjne: przy 0.79
#               retracementu cena czesto jest juz po drugiej stronie EMA20 15m)
BIAS_AT = "prev_close"
BIAS_TFS = ("1h", "4h", "1d")  # ktore TF musza byc zgodne (podzbior 15m/1h/4h/1d).
                               # Pod BOS (1h,4h,1d) bilo +$1104/PF 1.71 vs +$554 dla 4xTF (2026-06-26)

# --- filtr sesji (killzone) ---
# Wpuszczaj wejscia tylko w realnych sesjach ICT; martwe godziny pod BOS daly 7 tr/0 W/-$336.
# Nazwy musza pasowac do funkcji killzone() w engine.py: London / NY AM / NY Lunch / NY PM / Asian.
SESSION_FILTER = True
TRADE_SESSIONS = ("London", "NY AM", "NY PM", "Asian")  # bez "NY Lunch" (0 tr, ICT go unika)

# --- wyjscia (SL/TP) ---
# "fib":       SL = SL_FIB*nogi, TP = TP_FIB*nogi (dotychczasowe).
# "liquidity": SL za chronionym swingiem + bufor; TP na najblizszej przeciwnej plynnosci
#              (PDH/PDL / przeciwny swing / origin nogi) z clampem R i fallbackiem na fib.
# Sweep 2026-06-26: "liquidity" = +$2067/PF 3.01 (deny=allow, brak niejednoznacznosci intrabar)
# vs "fib" +$1401 — dodatni w obu widelkach, 3/1 mies. -> default.
EXIT_MODE = "liquidity"
SL_BUFFER_TICKS = 4       # bufor za swingiem w trybie "liquidity"
TP_MIN_R = 1.0            # min R targetu plynnosci (inaczej fallback na fib TP)
TP_MAX_R = 4.0            # max R targetu plynnosci (clamp dalekich celow)

# --- filtr wejscia ---
# "legacy": 15m FVG lub NWOG lub key_open (dotychczas). "none": kazdy cross (wieksza probka).
# "loose":  legacy + nizszy prog FVG/szersze key_open. "sweep": confluence ICT — przed OTE cena
#           zmiotla plynnosc (PDL/sesyjny low/swing low dla long; odwrotnie short) i ja odzyskala.
ENTRY_FILTER_MODE = "legacy"
SWEEP_LOOKBACK = 12       # ile barow 15m wstecz szukac zmiecenia+reclaim (tryb "sweep")

# --- wyjscia czasowe / trailing ---
MAX_HOLD_BARS = None      # None=off; po N barach 15m zamknij po cenie rynkowej (ucina dlugie bleedery)
EXIT_ON_SESSION_END = False  # zamknij gdy bar wyjdzie poza TRADE_SESSIONS
TRAIL_TO_SWING = False    # przesuwaj SL do ostatniego przeciwnego swingu (gdy w zysku)

# --- koszty / egzekucja ---
SLIPPAGE_TICKS_ENTRY = 1  # poslizg na wejsciu (adverse)
SLIPPAGE_TICKS_STOP = 1   # poslizg na SL (adverse); TP = limit, bez poslizgu
COMMISSION_RT = 0.74      # $ round-trip za kontrakt
BOTH_HIT_RULE = "sl_first"  # TP i SL w tym samym barze -> SL (konserwatywnie)
ENTRY_BAR_TP = "provable" # rozstrzyganie TP na barze wejscia:
                          # "deny":     TP najwczesniej od bara po wejsciu (dolna granica)
                          # "provable": TP tylko gdy fill na open bara i SL nietkniety —
                          #             wynik pewny niezaleznie od sekwencji intrabar (DOMYSLNE)
                          # "allow":    TP moze wypasc na barze wejscia (gorna granica)

# --- diagnostyka ---
POST_EXIT_BARS = 12       # okno (w barach 15m) szukania dotkniecia TP po wyjsciu na SL
