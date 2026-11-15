# Strategia "Fib OTE 0.79 + bias 4×TF" — wymogi

Instrument: **MNQ1!** (Micro E-mini Nasdaq-100, CME). Logika sygnałowa = 1:1 port z indykatora
"ICT Setup — NQ All-In-One" (`pine/ict_setup_nq_all_in_one.pine`).
Wszystkie czasy w **ET (America/New_York)**.

## 1. Kierunek — zgodność biasu na 4 timeframe'ach

Trade tylko, gdy bias na **15m, 1H, 4H i 1D** jest w tym samym kierunku (wszystkie LONG albo
wszystkie SHORT).

Bias TF = cena vs **EMA20 ostatniego zamkniętego bara danego TF**
(semantyka Pine `request.security(..., ta.ema(close,20)[1], lookahead_on)`):
- cena > EMA → LONG, cena < EMA → SHORT.

**Moment oceny** (`BIAS_AT`, domyślnie `prev_close`): zgodność 4×TF sprawdzana na
**zamknięciu bara poprzedzającego wejście** (= odczyt dashboardu indykatora przed uzbrojeniem
limitu na 0.79). Wariant `entry_price` (bias liczony w cenie wejścia) jest dostępny w configu,
ale przy 79% retracemencie cena jest zwykle z powrotem po drugiej stronie EMA20 15m, co
odrzuca niemal wszystkie sygnały (w teście: 4 trade'y vs 20 na tych samych danych).

## 2. Noga Fibonacciego (15m)

Jak w indykatorze (`f_fib_state`, pivoty 5/5, stan z zamkniętych barów 15m):
- **Long-leg**: ostatni potwierdzony pivot low → kroczące maksimum od tego pivota.
- **Short-leg**: ostatni potwierdzony pivot high → kroczące minimum od tego pivota.
- Kierunek nogi = wspólny bias (jak `fib_dir_src` w indykatorze).

Konwencja retracementu (pozycja fibo):
- short-leg: `poziom(r) = L + r·(H−L)` — 0 na dołku, 1.0 na swing high;
- long-leg: `poziom(r) = H − r·(H−L)` — 0 na szczycie, 1.0 na swing low.

## 3. Wejście / TP / SL (pozycje fibo nogi)

| Element | Pozycja fibo | Short (przykład) | Long (przykład) |
|---|---|---|---|
| Entry (limit) | **0.79** | `L + 0.79·(H−L)` | `H − 0.79·(H−L)` |
| Take Profit | **0.25** | `L + 0.25·(H−L)` | `H − 0.25·(H−L)` |
| Stop Loss | **1.0** (origin swing) | `H` | `L` |

RR teoretyczne: zysk 0.54 nogi / ryzyko 0.21 nogi ≈ **2.57R**.
Poziomy zamrażane w momencie wejścia (późniejsza zmiana nogi nie rusza TP/SL).

## 4. Filtr dodatkowy — min. jeden warunek spełniony w cenie/momencie wejścia

**(a) Strefa:** cena entry wewnątrz:
- 15m **FVG zgodnego z kierunkiem** (short → bearish FVG, long → bullish FVG),
  stan *active* lub *mitigated* (NIE inverted), min. rozmiar **8 pt** (jak `fvg_min`); stan
  oceniany wg zamkniętych barów sprzed bara wejścia; **lub**
- niewypełnionego **NWOG** (gap piątek 17:00 close → niedziela 18:00 open ET; ostatnie 3).

**(b) Key open:** `|cena entry − cena key open| ≤ 20 ticków = 5.0 pt` **i** czas wejścia w oknie
**[open, open + 1h]**. Key opens: **00:00, 10:00, 18:00 ET** (open bara 15m otwierającego sesję,
np. open 10:00 obowiązuje między 10:00 a 11:00).

## 5. Zarządzanie pozycją

- Maks. **1 pozycja** naraz; **1 wejście na nogę** (id nogi = czas pivota origin) — po TP/SL brak
  re-entry, dopóki nie powstanie nowa noga.
- Wyjście wyłącznie TP albo SL (brak time-stopa — odnotowane jako ryzyko w AUTOMATION.md).
  Opcjonalny break-even `BE_AT_FIB` (domyślnie off): gdy domknięty bar osiągnie poziom nogi,
  SL przesuwa się na entry od kolejnego bara (R nadal liczone od pierwotnego ryzyka `risk_pt`).
- Fill: limit na poziomie 0.79, gdy bar 15m dotknie poziomu (gap przez poziom → fill po open bara).
- **Gap-guard** (`GAP_GUARD=True`): gdy fill wypada już na/za poziomem SL (np. niedzielna luka
  przez limit i SL naraz), wejście jest pomijane — odpowiednik skasowania pending limitu przez
  robota; noga zostaje skonsumowana.
- Bramka `MIN_LEG_PT` (domyślnie 0 = off): pomija wejścia na nogach mniejszych niż próg
  (stop = 0.21 nogi, więc małe nogi → stopy w szumie 1 bara); noga NIE jest konsumowana.
- Rozstrzyganie TP na barze wejścia (`ENTRY_BAR_TP`): headline = **"provable"** — TP uznawany
  tylko, gdy fill był na open bara i SL nietknięty w tym barze (wynik pewny przy dowolnej
  ścieżce intrabar); "deny"/"allow" raportowane jako widełki. TP i SL w tym samym barze → **SL**
  (`BOTH_HIT_RULE="sl_first"`).

## 6. Instrument i koszty (config)

| Parametr | Wartość |
|---|---|
| Kontrakt | 1× MNQ ($2/pkt, tick 0.25 = $0.50) |
| Poślizg | 1 tick na wejściu + 1 tick na SL (TP = limit, bez poślizgu) |
| Prowizja | $0.74 round-trip |

## 7. Parametry konfigurowalne (backtest/config.py)

`ENTRY_FIB=0.79`, `TP_FIB=0.25`, `SL_FIB=1.0` (>1.0 = bufor za swingiem), `MIN_LEG_PT=0` (off),
`PIVOT_LEN=5`, `FVG_MIN_PT=8.0`, `KEY_OPEN_MAX_TICKS=20`, `KEY_OPEN_WINDOW_MIN=60`, `NWOG_KEEP=3`,
`EMA_LEN=20`, `BIAS_TFS=("15m","1h","4h","1d")` (podzbiór TF biasu), `BIAS_AT="prev_close"`,
`GAP_GUARD=True`, `SKIP_FIRST_BAR_AFTER_WEEKEND=False`, `BE_AT_FIB=None`,
`ENTRY_BAR_TP="provable"`, `BOTH_HIT_RULE="sl_first"`, `POST_EXIT_BARS=12`, koszty.
Porównanie wariantów: `run_backtest.py --sweep` (siatka × rozstrzygnięcia deny/provable/allow).

## 8. Założenia / ograniczenia backtestu

- Symulacja na barach **15m** (sekwencja zdarzeń wewnątrz bara nieznana → reguły z pkt 5;
  tryb "provable" rozstrzyga jedynie przypadki pewne path-independent). Dane: kontrakt ciągły
  MNQ1! z TradingView (back-adjusted wg ustawień TV).
- Bias w momencie wejścia liczony dla ceny entry (Pine porównuje live close z EMA[1]).
- Wyniki brutto nie uwzględniają przerw serwisowych CME (17:00–18:00 ET) — pozycje przenoszone.
- Diagnostyka w results.json: MAE/MFE per trade, `post_tp_bars` (po ilu barach od SL cena dotknęła
  pierwotnego TP; 0 = ten sam bar), **shadow trades** = sygnały bias+0.79 odrzucone filtrem,
  symulowane identycznie per-sygnał (porównanie jakości filtra, NIE krzywa kapitału).
