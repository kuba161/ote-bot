# ote_bot — instrukcja obsługi

Backtest strategii **„Fib OTE 0.79 + bias struktury"** na MNQ (Micro Nasdaq), port 1:1 logiki
z indykatora TradingView „ICT Setup — NQ All-In-One". Python **bez żadnych zależności zewnętrznych**
(stdlib only), wynik ląduje w statycznym dashboardzie w `site/`.

> ## ⚠️ Status: NIE handlować tego na żywo
> Stara próba (1.03–11.06.2026), na której dobierano parametry, daje **+$2507 / PF 2.48 / 25 trade'ów**.
> **Test forward (runda 6, 18.10.2026)** na zamrożonych parametrach i nigdy niewidzianych danych
> 30.06–16.10 dał **+$469 / PF 1.34 / 20 trade'ów**. To wynik dodatni w obu widełkach (deny $469 / allow $909),
> ale expectancy spadła do **23%** ($100 → $23/trade), miesiące wyszły 2 na plusie i 2 na minusie, a **bez jednego najlepszego
> trade'a wynik jest −$30**. Przewaga przeżyła, ale ledwo. Dalej: forward-test na demo.
> Szczegóły: `./venv/bin/python validate_forward.py` i karta „Test forward" na dashboardzie.

---

## 1. Szybki start — 3 komendy

```bash
cd ote-bot
./venv/bin/python backtest/run_backtest.py       # policz backtest, zapisz wyniki do site/
python3 -m http.server 8420 --directory site     # odpal dashboard (terminal zostaje zajęty)
```

W drugim oknie terminala albo po prostu w przeglądarce:

```bash
open http://localhost:8420
```

Trzy rzeczy, o których łatwo zapomnieć:

- **`./venv/bin/python`, nie samo `python3`** — projekt ma własny venv (Python 3.9). Choć sam kod jest
  stdlib only i pod systemowym `python3` też policzy się tak samo (sprawdzone), venv jest tym, co
  gwarantuje ten sam wynik co zawsze, i to w nim siedzi `pytest`.
- **Najpierw backtest, potem serwer** — dashboard tylko czyta `site/results.json`. Bez przeliczenia
  pokaże stare liczby albo pustkę.
- **Serwer trzyma terminal** — kończysz go `Ctrl+C`. Nic się przez to nie psuje, dane są już na dysku.

---

## 2. Jak czytać wynik

`run_backtest.py` wypisuje dokładnie to (realny przebieg z 21.09.2026, czyli jeszcze na samej starej próbie;
od 18.10 dane sięgają 16.10 i liczby są inne: 45 tr, +$2976, PF 1.97):

```
Instrument: MNQ ($2.0/pkt)
Dane: 15m=6741  1H=6538  4H=5299  1D=1789
Okno 15m: 2026-03-01 18:00 -> 2026-06-11 11:45 ET
Struktura: FVG(>=8.0pt)=880  NWOG=14  key opens=221
Lejek: {'bars': 6315, 'bias_aligned': 1799, 'cross': 219, 'rej_min_leg': 0, 'rej_gap_guard': 37,
        'rej_maxrisk': 0, 'rej_filter': 157, 'rej_weekend': 0, 'rej_session': 3013,
        'shadow': 57, 'entries': 25}

=== WYNIKI (headline = provable) ===
Trades: 25  (W 10 / L 15, winrate 40.0%)
PnL: $2507.29   PF: 2.48   expectancy: $100.29/trade
avg R: 0.693   maxDD: $529.92
Widelki intrabar: deny $2507.29 (PF 2.48)  |  allow $2507.29 (PF 2.48)
Shadow (bez filtra, per-sygnal): 57 sygnalow, PnL $230.29, WR 22.8%, PF 1.04

Filtry: {'fvg': 18, 'key_open': 2, 'nwog': 5}
Strony: {'short': 8, 'long': 17}
```

Co znaczy która linijka:

| Linijka | Czytaj tak |
|---|---|
| **Okno 15m** | Ile historii w ogóle mamy. Dziś 1.03–11.06.2026 = **102 dni**. To jest źródło wszystkich zastrzeżeń — TV nie daje więcej 15m. |
| **Lejek** | Gdzie giną sygnały. Z 6315 barów bias był zgodny na 1799, cena dotknęła 0.79 w 219 przypadkach, **filtr sesji odrzucił 3013**, filtr wejścia (FVG/NWOG/key open) 157, gap-guard 37 → **25 wejść**. Jak nagle masz 0 trade'ów, tu widać, który filtr to zjadł. |
| **PF** (profit factor) | Suma zysków / suma strat. >1 = zarabia. 2.48 brzmi świetnie, ale na 25 trade'ach to nadal mała próba. |
| **expectancy** | Średni wynik na trade. To jest liczba, która musi zostać dodatnia poza próbką — i to ona wywróciła się w walk-forwardzie ($100 → −$12). |
| **avg R** | Średni wynik w jednostkach ryzyka. Niezależny od wielkości pozycji, więc porównywalny między konfiguracjami sizingu. |
| **maxDD** | Największe obsunięcie kapitału po drodze. Tyle musisz wytrzymać, żeby dojechać do tego PnL. |
| **Widełki intrabar deny \| allow** | Backtest na świecach 15m nie wie, czy w spornym barze pierwszy był TP czy SL. `deny` = zawsze na Twoją niekorzyść, `allow` = zawsze na korzyść. **Prawda jest między nimi.** Dziś obie są sklejone ($2507 = $2507), bo wyjścia płynnościowe usunęły niejednoznaczność — ale jeśli kiedyś się rozjadą, patrz na `deny`. |
| **Shadow** | Sygnały, które filtr wejścia **odrzucił**, policzone tak, jakby jednak weszły. PF 1.04 = filtr odrzucał rzeczy mniej więcej neutralne, czyli robi swoją robotę. (W czerwcu 2026 było odwrotnie — shadow bił realne trade'y i to był sygnał, że filtr jest zły.) |
| **Filtry / Strony** | Który warunek wpuścił trade i w którą stronę. Pilnuj, żeby zysk nie siedział w jednym koszyku. |

Wynik zapisuje się do **`site/results.json`** (czyta go dashboard) i **`site/trades.csv`** (otwierasz
w Excelu, trade po trade).

---

## 3. Pozostałe komendy

Wszystkie z katalogu `ote-bot` (katalog repo).

```bash
# siatka wariantów parametrów × 3 rozstrzygnięcia intrabar (deny/provable/allow)
./venv/bin/python backtest/run_backtest.py --sweep

# ten sam backtest na innym instrumencie (MES na razie nie zadziała — patrz niżej)
./venv/bin/python backtest/run_backtest.py --instrument mes

# WALK-FORWARD: parametry dobierane tylko na "train", ocena na osobnym kawałku czasu
./venv/bin/python validate_wf.py              # domyślny split 60/40
./venv/bin/python validate_wf.py --frac 0.5   # inne cięcie
# → site/wf.json + werdykt GO/NO-GO na końcu wydruku

# TEST FORWARD: zamrożone defaulty na danych PO starej próbie (data/archive/) + hipotezy z R5
./venv/bin/python validate_forward.py         # → site/forward.json + werdykt

# MONTE CARLO: rozkład wyników przy losowaniu kolejności trade'ów
./venv/bin/python validate_mc.py

# osobna analiza: fade Midnight Open (linia 0:00 ET) przy dotknięciu o 8:30
./venv/bin/python3 backtest/midnight_open_830.py   # → site/mo830.json

# testy (57: test_engine 41 + test_validate 6 + test_forward 10)
./venv/bin/python -m pytest backtest/
```

**Uwaga do `--sweep`:** to jest narzędzie do *pytania*, nie do *zmieniania*. Zasada, którą sam
ustaliłeś: default w `config.py` zmieniamy dopiero gdy wariant jest **dodatni w OBU widełkach
(deny i allow)** i **stabilny między miesiącami** — nigdy po samym maksymalnym PF na ~25 trade'ach.

**Uwaga do `validate_mc.py`:** Monte Carlo mówi ładnie („95% serii dodatnich, ryzyko ruiny ~0% dla
konta ≥$2k"), ale jest **okrężne** — resampluje w kółko te same 25 trade'ów, więc opisuje rozkład
*wewnątrz* próby, a nie to, czy strategia działa na nowych danych. Zdaniem na temat generalizacji
jest wyłącznie `validate_wf.py`.

**Uwaga do `--instrument mes`:** infrastruktura jest gotowa, ale brakuje plików `data/mes_*.csv`.
Eksport z TradingView trzeba zrobić ręcznie (tą samą metodą co MNQ), potem to jedno polecenie.

---

## 4. Co gdzie leży

```
ote_bot/
├── backtest/
│   ├── config.py            ← WSZYSTKIE pokrętła strategii (tu się majstruje)
│   ├── engine.py            ← silnik: bias, pivoty, fib, FVG, wejścia, zarządzanie pozycją
│   ├── run_backtest.py      ← punkt wejścia: backtest + sweep, zapisuje site/
│   ├── midnight_open_830.py ← osobna analiza, niezwiązana ze strategią Fib
│   ├── test_engine.py       ← 41 testów silnika
│   ├── test_validate.py     ← 6 testów walidacji (split, brak leaku, plateau)
│   └── test_forward.py      ← 10 testów: kawałki po dziurach, scalanie, test forward
├── data/                    ← mnq_{15m,1h,4h,1d}.csv (scalone) + archive/ (stara próba) + raw/ (eksporty z TV)
├── site/                    ← dashboard: index.html + app.js, dane w results.json / wf.json /
│                              mo830.json, trades.csv do Excela
├── validate_wf.py           ← walk-forward out-of-sample (R5: NO-GO na starej próbie)
├── validate_forward.py      ← test forward na danych po zamrożeniu parametrów (R6)
├── merge_data.py            ← skleja data/archive + data/raw w data/mnq_*.csv (kontrola nakładek)
├── validate_mc.py           ← Monte Carlo
├── venv/                    ← własny venv (Python 3.9); praktycznie tylko po to, żeby mieć pytest
├── REQUIREMENTS.md          ← pełna reguła strategii, krok po kroku
└── AUTOMATION.md            ← trzy drogi do robota (alerty TV / API brokera / paper bot) + rekomendacja
```

---

## 5. Pokrętła w `backtest/config.py`

Aktualne defaulty — to jest konfiguracja, z której bierze się headline:

| Parametr | Wartość | Co robi |
|---|---|---|
| `ENTRY_FIBS` | `(0.79,)` | Poziomy wejścia. Krotka = scale-in (strefa OTE). `(0.705, 0.79)` daje 57 trade'ów i $3159, ale niższy PF (2.02) i wyższy DD — leży jako opcja. |
| `BIAS_METHOD` | `"BOS"` | Skąd bias: stanowy break of structure. Alternatywy: `"HH/HL"` (za restrykcyjne — bywa 0 trade'ów), `"EMA20"` (stara logika, gorsza). |
| `BIAS_TFS` | `("1h","4h","1d")` | Na których TF bias musi być zgodny. |
| `SESSION_FILTER` / `TRADE_SESSIONS` | `True` / London, NY AM, NY PM, Asian | Odcina martwe godziny (bez tego 7 trade'ów, 0 wygranych, −$336). |
| `EXIT_MODE` | `"liquidity"` | SL za swingiem + bufor, TP na najbliższej płynności (PDH/PDL). Alternatywa `"fib"` jest słabsza. |
| `SIZING_MODE` | `"risk"` | Wielkość pozycji ze stałego ryzyka w $, nie stała liczba kontraktów. |
| `RISK_PER_TRADE_USD` | `100` | Liniowa gałka zysk/obsunięcie: $75→DD ~$406, $100→DD ~$530, $150→DD ~$858. |
| `MAX_RISK_USD` | `400` | Skip trade'ów o skrajnie szerokim stopie. |
| `PIVOT_LEN` / `STRUCT_PIVOT_LEN` | `5` / `5` | Pivoty N/N do wykrywania swingów (fib / bias). |
| `GAP_GUARD` | `True` | Nie wchodź, gdy fill jest już za SL (niedzielne luki) — odpowiednik anulowania limitu przez robota. |

Kilka pokręteł istnieje tylko do badań i jest **świadomie wyłączonych**, bo dane je odrzuciły:
`BOS_DISPLACEMENT` (−$502), filtr `"sweep"` (−$716), `MAX_HOLD_BARS` / `EXIT_ON_SESSION_END` /
`TRAIL_TO_SWING` (ucinały runnery). Nie włączaj ich „bo brzmią sensownie" — były sprawdzone.

---

## 6. Gdy coś nie działa

**„Port zajęty" / „widzę stare wyniki, mimo że przeliczyłem"**
Stary serwer nadal chodzi i to on odpowiada.
```bash
lsof -i :8420
pkill -f "http.server 8420"
```
Dashboard chodzi na porcie **8420**.

**„Przeglądarka pokazuje stare dane"**
`python3 -m http.server` nie wysyła nagłówków cache, więc przeglądarka trzyma stary `app.js`.
Twarde odświeżenie: **Cmd+Shift+R**.

**„Nie ma venv / venv się rozsypał"**
Nic strasznego — kod jest **stdlib only**, więc to zadziała od ręki:
```bash
python3 backtest/run_backtest.py
```
(sprawdzone na systemowym Pythonie 3.14 — ten sam wynik co z venv). venv odtwarzasz tak:
```bash
python3 -m venv venv && ./venv/bin/pip install pytest
```

**„Dashboard pusty / same zera"**
Albo nie poszedł `run_backtest.py`, albo serwer patrzy w zły katalog. Musi być
`--directory site`, uruchamiane z `ote_bot/`. Sprawdzenie na sucho:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8420/results.json   # ma być 200
```

**„Brak danych" / błąd przy wczytywaniu CSV**
W `data/` muszą leżeć cztery pliki: `mnq_15m.csv`, `mnq_1h.csv`, `mnq_4h.csv`, `mnq_1d.csv`.
Są sklejane przez `merge_data.py` z `data/archive/` (stara próba, zamrożona) i `data/raw/` (eksporty).

**Odświeżenie danych z TradingView** (TV Desktop musi chodzić z CDP, np. `tv_launch` z MCP):
```bash
node tools/tvexport.mjs 'CME_MINI_DL:MNQ1!' data/raw mnq 15 60 240 1D
# dopisz nowe pliki do SOURCES w merge_data.py, potem:
python3 merge_data.py --check    # raport nakładek i dziur, bez zapisu
python3 merge_data.py            # zapis data/mnq_*.csv
```
Eksporter sam przywraca symbol i interwał wykresu. **Limit TV: ~5000 barów 15m wstecz (~2,5 mies.).**
Żeby nie zrobić dziury, eksportuj **co najmniej raz na 2 miesiące**. Starszą historię da się wyciągnąć
z wygasłego kontraktu (np. `MNQU2026`), bo MNQ1! jest nieadjustowany i między rolkami = kontrakt frontowy.
Tak załatano lipiec. `merge_data.py` zatrzyma się, jeśli OHLC na nakładce się nie zgadza (inna seria).
Dziurę dłuższą niż 4 dni silnik i tak omija (`run_segmented` liczy każdy ciągły kawałek osobno).

---

## 7. Gdzie jesteśmy i co dalej

Krótka historia, żeby nie powtarzać zamkniętych wątków:

1. **Runda 1 (12.06.2026)** — przebudowa silnika: tryb „provable", gap-guard, shadow trades, sweep.
   Ujawniło, że `SL_FIB` był martwym parametrem, a filtr wejścia odrzucał lepsze sygnały niż przepuszczał.
2. **Runda 2 (26.06)** — bias z EMA20 na strukturę rynku (BOS), filtr sesji, wyjścia płynnościowe.
   +$2067, PF 3.01. `BOS_DISPLACEMENT` sprawdzony i odrzucony.
3. **Runda 3 (26.06)** — position sizing wg ryzyka ($100/trade, cap $400) → +$2507, PF 2.48.
   Wyjścia czasowe i trailing sprawdzone i odrzucone (cięły runnery).
4. **Runda 4 (26–27.06)** — test wrażliwości (defaulty siedzą na pikach, więc live będzie niższe niż
   backtest), OTE jako strefa (`ENTRY_FIBS`), parametryzacja instrumentu.
5. **Runda 5 (27.06)** — uczciwy walk-forward. **NO-GO.** I najciekawsze: to, co optymalizacja odrzuciła,
   okazało się **robustniejsze** poza próbką (bias na 4×TF, pivoty 3–4). Klasyczny podpis przeuczenia.
6. **Runda 6 (18.10)** — nowe dane do 16.10 i **test forward** na zamrożonych parametrach: +$469, PF 1.34,
   20 tr, dodatni w obu widełkach, ale słaby i oparty na jednym trade. Hipoteza 4×TF z R5 **nie przeżyła**
   (−$440). Pivot 4 wypadł najlepiej i na IS, i na forward, ale defaultu nie zmieniam. Szczegóły w `WIEDZA.md`.
7. **Runda 7 (15.11)** — dane do 13.11. W listopadzie 6 shortów, wszystkie na SL (−$1009), więc forward
   30.06–13.11 spadł do **−$540, PF 0.77, 26 tr → NO-GO**. Wszystkie warianty hipotez ujemne. Szczegóły w `WIEDZA.md`.

**Trzy realne następne kroki** (szerzej w `AUTOMATION.md`):

- **#1 więcej danych 15m** — konieczne. 102 dni to za mało na jakikolwiek werdykt. Źródła: Tradovate
  historical API albo IBKR.
- **#3 forward-test na papierze** — Tradovate demo, z `backtest/engine.py` użytym jako biblioteka
  sygnałów. Jedyny sposób, żeby rozstrzygnąć widełki intrabar naprawdę.
- **MES jako walidacja krzyżowa** — `--instrument mes` gotowe, brakuje wyeksportowanych danych.

Wskazówka z rundy 5 **do retestu, gdy będzie więcej danych** (nie do zmiany teraz, bo optymalizowanie
na zbiorze OOS to ten sam błąd od drugiej strony): spróbować `BIAS_TFS` = 4×TF + `PIVOT_LEN` 3–4.

---

## 8. Ściąga — wszystko w jednym miejscu

```bash
cd ote-bot
./venv/bin/python backtest/run_backtest.py            # backtest
./venv/bin/python backtest/run_backtest.py --sweep    # warianty parametrów
./venv/bin/python validate_wf.py                      # walk-forward OOS (werdykt GO/NO-GO)
./venv/bin/python validate_mc.py                      # Monte Carlo
./venv/bin/python3 backtest/midnight_open_830.py      # analiza Midnight Open 8:30
./venv/bin/python -m pytest backtest/                 # 57 testów
python3 -m http.server 8420 --directory site          # dashboard → http://localhost:8420
pkill -f "http.server 8420"                           # ubij serwer, gdy port zajęty
```
