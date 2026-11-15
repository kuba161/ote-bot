# Automatyzacja strategii "Fib OTE 0.79 + bias 4×TF" — możliwości budowy robota

Stan: backtest gotowy (patrz `REQUIREMENTS.md` + dashboard `site/`). Ten dokument opisuje drogi
do w pełni automatycznego robota i rekomendację. **Decyzja i implementacja = następny etap.**

## Wnioski z backtestu, które wpływają na automatyzację

Okno 1.03–11.06.2026 (3,3 mies., tyle 15m historii daje TV), MNQ 1 kontrakt, koszty wliczone.
Stan po przebudowie silnika 2026-06-12 (gap-guard, tryb "provable", shadow trades, sweep):

| Wariant (defaulty config.py) | Trades | Winrate | PnL | PF | maxDD |
|---|---|---|---|---|---|
| Headline: provable + gap-guard | 18 | 22% | **-$253** | 0.69 | $367 |
| Widełki: deny / allow | 18 | 22% / 39% | -$253 / **+$588** | 0.69 / 2.00 | — |

(Stara baza 2026-06-11: 20 trade'ów, -$256/+$585 — gap-guard wycina teraz 2 martwe wejścia
po niedzielnych lukach, stąd 18.)

- Tryb "provable" nie przyznał ŻADNEGO spornego TP — wszystkie 3 sporne wejścia były fillami
  w środku bara → różnicę deny/allow **rozstrzygnie tylko 1m albo paper-live** (bez zmian).
- **Sweep (`run_backtest.py --sweep`, 16 wariantów × 3 rozstrzygnięcia)**: jedyne warianty
  dodatnie w OBU widełkach to `bias_4h_1d` (52 tr., deny +$267 / PF 1.12, allow +$1110 / PF 1.55,
  3/1 mies.) i combo `bias42_leg100` = bias 4H+1D + MIN_LEG_PT=100 (36 tr., deny +$344 / PF 1.19,
  allow +$1086 / PF 1.66, 3/1 mies.). Bufor SL (1.05/1.1), inne TP (0.5/0.0) i BE(0.5) POGARSZAJĄ.
  Zmiana defaultów strategii = decyzja Kuby wg kryterium (dodatni w obu widełkach + stabilność
  miesięczna); próba nadal mała.
- **Shadow trades**: 67 sygnałów odrzuconych filtrem miało per-sygnał PF 1.22 (+$570, WR 31%)
  vs PF 0.69 realnych — filtr FVG/NWOG na tej próbie **odrzucał lepsze sygnały, niż przepuszczał**.
- Filtr key-open: nadal 0 trafień (po poluzowaniu `ko_loose` +2 trade'y bez przewagi) —
  kandydat do usunięcia z kodu przy porcie do paper bota.
- Krótkie nogi: zaimplementowane jako `MIN_LEG_PT` — monotoniczna poprawa 80→100→120
  (deny -$212→-$170→-$121), samo nie wystarcza, ale wzmacnia combo.
- Luki niedzielne: zaimplementowane jako **`GAP_GUARD`** w silniku (skip wejścia, gdy fill
  na/za SL = odpowiednik kasowania pending limitu przez robota; default ON).

## Opcje implementacji robota

### Opcja A — TradingView alerty → webhook → executor
Dodać do indykatora `alertcondition` "OTE 0.79 touch + filtr" (warunki już policzone w Pine),
alert z webhookiem → mały serwis (FastAPI) → API brokera futures.
- Plusy: logika liczona przez TV (parytet z wykresem za darmo), minimum kodu.
- Minusy: alerty TV trzeba ręcznie utrzymywać (po każdej edycji skryptu!), webhook wymaga
  publicznego endpointu (ngrok/VPS), TV nie zarządza pozycją (bracket SL/TP musi składać
  executor), opóźnienie alertów, brak kontroli "1 wejście na nogę" po stronie TV.

### Opcja B — lokalny bot na danych brokera (REKOMENDOWANA)
`backtest/engine.py` już jest deterministyczną biblioteką sygnałów (bias/leg/FVG/NWOG/key
opens — czysta funkcja barów 15m). Bot:
1. strumień barów 15m/1H/4H/1D z API brokera (Tradovate ma WebSocket + **darmowe demo** =
   paper trading; alternatywy: IBKR, Rithmic przez prop),
2. po każdym zamkniętym barze 15m: aktualizacja stanu → jeśli bias 4×TF zgodny → wystaw/
   aktualizuj **limit 0.79 + bracket (SL 1.0 / TP 0.25)**; kasuj limit gdy warunki znikną,
3. dziennik decyzji + Rich-dashboard w terminalu (wzorzec z `trading_agent/`).
- Plusy: pełna kontrola (1 pozycja, 1 wejście/nogę, kasowanie przy luce), ten sam kod co
  backtest (zero rozjazdu logiki), paper → micro live bez zmian.
- Minusy: dane brokera ≠ dane TV (kontrakt ciągły vs bieżący — bot powinien grać na
  bieżącym kontrakcie, np. MNQU2026, i liczyć strukturę na nim), trzeba napisać warstwę
  egzekucji.

### Opcja C — półautomat Claude + MCP (TV Paper Trading)
Claude przez MCP czyta dashboard indykatora i składa zlecenia w TV Paper Trading.
- Dobre do nadzorowanych testów na żywo, NIE do pracy bezobsługowej (wymaga działającej
  sesji TV Desktop + Claude w pętli; kruche).

## Rekomendowany plan (etapami)

1. **Walidacja intrabar**: dociągnąć 1m z TV (ostatnie ~2 tyg.) i odtworzyć ostatnie trade'y
   minuta po minucie → rozstrzygnąć wariant konserwatywny vs optymistyczny.
2. **Dłuższa próba**: backtest dłuższego okna gdy przybędzie danych 15m (eksport co ~3 mies.
   tym samym mechanizmem; skrypt i dane w `data/`) lub jednorazowo kupić/CSV z innego źródła.
3. **Paper bot (Opcja B)** na Tradovate demo, reużywając `engine.py`; 4-8 tygodni paper.
4. **Micro live** (1× MNQ) tylko jeśli paper potwierdzi dodatnią oczekiwaną wartość.

## Ryzyka

- Mała próba (20 trade'ów) — wynik backtestu nie jest dowodem przewagi.
- Wrażliwość na model wypełnień intrabar (patrz widełki wyników).
- Brak time-stopa: pozycja może wisieć dniami; brak flat na weekend (luka = ryzyko > 1R).
- Jednostronność okresów (kwiecień-maj prawie same longi) — bias 4×TF z natury gra z trendem.
- Dane TV (kontrakt ciągły, back-adjusted) vs realny kontrakt u brokera — poziomy mogą się
  różnić o kilka(naście) pkt w okresach rolowania.
