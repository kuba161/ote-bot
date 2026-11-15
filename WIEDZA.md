# ote_bot — cała wiedza o projekcie

Stan na **18.10.2026**. Ten plik jest pamięcią projektu: skąd się wziął, co zostało sprawdzone,
co **odrzucone przez dane**, jakie decyzje podjął Kuba i dlaczego. `README.md` obok mówi „jak to
uruchomić" — ten plik mówi **„dlaczego tak i czego już nie próbować"**.

Jeśli wracasz do projektu po przerwie (albo jesteś Claude'em w nowej sesji): przeczytaj rozdział 4
(„Cmentarz pomysłów") i 6 („Decyzje Kuby") zanim cokolwiek zaproponujesz.

---

## 1. Skąd się to wzięło

Kuba handluje metodyką ICT na Nasdaqu. Taktyka została najpierw **wyklikana i zweryfikowana wzrokowo
na TradingView**, w postaci własnego indykatora Pine „ICT Setup — NQ All-In-One"
(`pine/ict_setup_nq_all_in_one.pine`). Dopiero potem powstał ten
projekt: **backtest tej samej logiki, port 1:1**, żeby sprawdzić liczbami, czy to w ogóle ma przewagę,
i — docelowo — żeby zrobić z tego robota.

Parytet z indykatorem jest świadomy i trzeba go pilnować: te same pivoty 5/5, ta sama definicja biasu,
ten sam filtr FVG ≥8 pkt. **Zmiana logiki tutaj oznacza zmianę tam** (i odwrotnie) — inaczej wykres
pokazuje co innego, niż liczy backtest. Wyjątek zrobiony świadomie: `BOS_DISPLACEMENT` był testowany
tylko tutaj, wyszedł źle i **nie został wniesiony do Pine**.

Instrument: **MNQ1!** (Micro Nasdaq, $2/pkt). Dane: `data/mnq_{15m,1h,4h,1d}.csv`, okno
**1.03–11.06.2026 = 102 dni** (stara próba, zamrożona w `data/archive/`) + od R6 forward **30.06–16.10.2026** (dziura 12–30.06 w 15m).

---

## 2. Reguła strategii w dwóch zdaniach

Bias (struktura rynku) zgodny na wybranych wyższych TF → limit na **0.79 retracementu nogi Fib 15m**
(pivoty 5/5, running extreme) → wyjście płynnościowe (SL za swingiem, TP na najbliższej płynności
PDH/PDL). Wejście musi dodatkowo przejść filtr: **15m FVG** (≥8 pkt, zgodny kierunek) **albo NWOG**,
**albo** ≤20 ticków od key open (00:00 / 10:00 / 18:00 ET), i wypaść w jednej z sesji ICT.

Pełna specyfikacja: **`REQUIREMENTS.md`**. Parametry: **`backtest/config.py`** (tabela w `README.md`).

---

## 3. Historia rund — co się działo

| Runda | Data | Co weszło | Wynik |
|---|---|---|---|
| **R1** | 12.06.2026 | Przebudowa silnika: tryb „provable", `GAP_GUARD`, `MIN_LEG_PT`, `BE_AT_FIB`, MAE/MFE, shadow trades, sweep | −$253, PF 0.69 (bias = EMA20) |
| **bias** | 26.06.2026 | EMA20 → **struktura rynku (BOS)** | +$554, PF 1.42 — pierwszy raz dodatni w OBU widełkach |
| **R2** | 26.06.2026 | Filtr sesji, wyjścia płynnościowe, `BIAS_TFS=(1h,4h,1d)` | **+$2067**, PF 3.01, 25 tr |
| **R3** | 26.06.2026 | Position sizing wg ryzyka ($100/trade, cap $400) | **+$2507**, PF 2.48, maxDD $530 |
| **R4** | 26–27.06.2026 | Test wrażliwości, OTE jako strefa, parametryzacja instrumentu | bez zmiany defaultu |
| **R5** | 27.06.2026 | **Walk-forward out-of-sample** | **NO-GO** |
| **R6** | 18.10.2026 | Nowe dane do 16.10, **test forward** na zamrożonych parametrach | +$469, PF 1.34, 20 tr — **GO\* graniczny** |
| **R7** | 15.11.2026 | Dane do 13.11, forward przedłużony | −$540, PF 0.77, 26 tr — **NO-GO** (listopad: 6 shortów, 6× SL) |
| **R8** | 15.11.2026 | Partial/BE/bliższy TP + pivot 4 | nic nie przeszło kryterium; H4 pivot4+BE1R jedyny + na fwd (+$131/+$580) ale 1/5 mies. |

### R1 — przebudowa silnika (12.06)
Punkt wyjścia był zły nie dlatego, że strategia nie działa, tylko dlatego, że **silnik mierzył źle**:
- `SL_FIB` był **martwym parametrem** — silnik hardkodował stop na swingu i ignorował ustawienie
- niedzielne luki przez cały leg dawały **fantomowe zyski**, jeśli stop księgowano po cenie SL;
  teraz stopy wyceniane są po `max(SL, open)` / `min(SL, open)`, a `GAP_GUARD` w ogóle nie wpuszcza
  wejść, których fill leży już za stopem (odpowiednik anulowania limitu przez robota)
- doszedł tryb **„provable"**: TP na barze wejścia przyznawany tylko wtedy, gdy da się go udowodnić
  (fill na otwarciu i SL nietknięty). Stąd widełki **deny / allow** — patrz rozdział 7.

**Shadow trades** (symulacja sygnałów odrzuconych filtrem) pokazały wtedy rzecz nieprzyjemną:
67 odrzuconych sygnałów miało PF 1.22, a przepuszczone 0.69 — **filtr odrzucał lepsze sygnały,
niż wpuszczał**. To był argument za przebudową, nie za dokręcaniem.

### Zmiana biasu: EMA20 → struktura (26.06)
Największy pojedynczy skok jakości. Bias liczony z **break of structure** (close łamie ostatni swing
high/low → flip kierunku) zamiast „cena nad/pod EMA20". Wynik: **+$554 / PF 1.42** vs −$253 dla EMA20,
i po raz pierwszy **dodatni w obu widełkach** (+$330 / +$655) — czyli spełnione kryterium Kuby.
Wariant `BIAS_TFS=(1h,4h,1d)` był jeszcze mocniejszy: 37 trade'ów, +$1104, PF 1.71.
`"HH/HL"` na czterech TF dało **0 trade'ów** (za restrykcyjne). EMA20 zostało jako opcja fallback.

### R2 — sesje i wyjścia płynnościowe (26.06)
Analiza pokazała dwie dziury: (a) handel w martwych godzinach = 7 trade'ów, 0 wygranych, −$336;
(b) cały zysk siedział na czterech wejściach typu key open. Weszły: **filtr sesji**
(London / NY AM / NY PM / Asian, reuse `killzone()` z silnika) i **`EXIT_MODE="liquidity"`**
(SL za swingiem + bufor, TP na najbliższej płynności — PDH/PDL lub przeciwny kraniec nogi —
z clampem R i fallbackiem na fib).

Efekt uboczny, ważny: **widełki deny/allow się skleiły** ($2067 = $2067). Wyjścia płynnościowe
usunęły niejednoznaczność intrabar, więc rozstrzyganie na danych 1-minutowych przestało być potrzebne.

Miesiące: 03 +$1225 · 04 +$611 · 05 +$384 · 06 −$154. Obie strony dodatnie (short z −$101 na +$1105).

### R3 — position sizing wg ryzyka (26.06)
Ryzyko na trade wahało się **16-krotnie** ($21–$329), bo pozycja była stała, a stopy różnej szerokości.
`SIZING_MODE="risk"` liczy liczbę kontraktów ze stałego ryzyka w dolarach.

Tu wydarzyła się rzecz warta zapamiętania. Po włączeniu sizingu PnL **spadł** $2067 → $1962 i wyglądało
to jak pogorszenie. **To był artefakt skali, nie utrata przewagi**: suma R (zysk w jednostkach ryzyka,
niezależny od sizingu) wyniosła 18.2R dla sizingu ryzykiem vs 17.3R dla stałej pozycji — czyli
**lepiej**. Winny był cap `MAX_RISK_USD=200`, który wycinał jeden dobry trade z szerokim stopem.
Po podniesieniu capa do **$400**: **+$2507 przy tym samym maxDD $530**.

`RISK_PER_TRADE_USD` jest liniową gałką zysk/obsunięcie: $75 → $2450 / DD $406 · $100 → $2507 / DD $530
· $150 → $3628 / DD $858 (powyżej $150 efektywność spada). **Kuba wybrał $100** jako zrównoważony.

### R4 — robustness (26–27.06)
Test wrażliwości: defaulty siedzą na **pikach** (`ENTRY_FIB` 0.75 → $1012, **0.79 → $2507**, 0.83 → $1361;
`PIVOT_LEN`/`STRUCT_PIVOT_LEN` = 5 też pik). Przewaga jest dodatnia przy każdej sąsiedniej wartości,
więc się nie wywraca — ale **realnie live będzie niższe niż backtest**, orientacyjnie $1000–2000.

Powstała **OTE jako strefa** (`ENTRY_FIBS` = krotka transz, każda 1/N budżetu ryzyka, `run_entry_zone()`).
Wariant `(0.705, 0.79)`: **57 trade'ów** (2,3× większa próba!), $3159, PF 2.02, dodatni w obu widełkach.
Przechodzi kryterium, ale to kompromis: więcej próbki i zysku, za to niższy PF (2.02 vs 2.48) i wyższy
DD (~$1239 vs $530). **Default został `(0.79,)`**, strefa jest opcją.

### R5 — uczciwa walidacja (27.06) → **NO-GO**
`validate_wf.py`: anchored walk-forward — parametry wybierane **wyłącznie na train**, ocena na osobnym,
nigdy niewidzianym kawałku czasu.

| Split | TRAIN | OOS |
|---|---|---|
| 60/40 (granica 01.05) | +$2589, PF 3.38, 18 tr | **−$82, PF 0.87, 7 tr** |
| 50/50 (granica 21.04) | +$2270, PF 4.01, 13 tr | +$237, PF 1.25, 12 tr |

Expectancy przewraca znak ($144 → −$12/tr) albo spada dziewięciokrotnie ($175 → $20/tr) — **zależnie
od cięcia**. Czyli: przewaga jest skoncentrowana w marcu–kwietniu, a poza próbką marginalna i niestabilna.

Sanity check przeszedł: PnL(train) + PnL(test) = $2507 = headline, podział rozłączny po `entry_ts`,
parametry zamrożone, brak leaku.

### R6 — nowe dane + test forward (18.10) → **GO\* graniczny**
Dane dociągnięte do **16.10.2026** (`tvexport.mjs` + `merge_data.py`). Parametry zamrożone 27.06,
więc wszystko po 11.06 to czysty out-of-sample, którego R5 nie miał. Nic w `config.py` się nie zmieniło.

**Dane.** TV oddaje dziś tylko ~5000 barów 15m wstecz, więc MNQ1! zaczyna się od 02.08. Lipiec
załatany wygasłym **MNQU2026**: MNQ1! jest nieadjustowany, więc między rolkami (14.06 → 14.09)
to dokładnie kontrakt frontowy. Zgodność sprawdzona co do ticka (2836 barów 15m, 1506 barów 1h,
0 rozjazdów). Stare i nowe MNQ1! na 1h/4h/1d też są identyczne, z wyjątkiem ostatniego baru starego
eksportu, który był niedomknięty. **Dziura 11.06–30.06 w 15m zostaje** (nie da się jej odzyskać z TV).
Silnik omija ją przez `run_segmented`: każdy ciągły kawałek 15m liczony osobno, z rozbiegiem 96 barów.
Stara próba odtwarza się co do centa ($2507.29) zarówno z `data/archive/`, jak i jako pierwszy kawałek scalonych danych.

| | trades | PnL | PF | WR | exp/tr | avg R | maxDD |
|---|---|---|---|---|---|---|---|
| IS 1.03–11.06 | 25 | +$2507 | 2.48 | 40% | $100 | 0.69 | $530 |
| **Forward 30.06–16.10** | **20** | **+$469** | **1.34** | 30% | **$23** | 0.16 | $496 |
| forward deny / allow | | $469 / $909 | 1.34 / 1.71 | | | | |

- Miesiące: 07 +$395 · 08 −$17 · 09 **−$479** · 10 +$570 (2/4 na plusie).
- **Bez najlepszego trade'a (+$499, short 22.07) forward = −$30.** Przewaga wisi na pojedynczych runnerach,
  czyli zgodnie z tym, jak ta strategia zarabia, ale przy 20 trade'ach to cienko.
- Widełki **rozjechały się** ($469 / $909), a na IS były sklejone. Znaczy to, że w nowych danych są sporne bary
  intrabar. Wiążąca jest liczba deny.
- Rynek w oknie forward −4,6% (IS +16,3%). Strategia wzięła 16 longów (−$13) i 4 shorty (+$482). Zysk nie
  pochodzi z jechania trendem, ale też nie z longów, które dominują liczbowo.
- Walk-forward 60/40 na scalonych danych (granica 24.07): OOS **+$145, PF 1.12, 17 tr**, exp $101 → $9.
  `validate_wf` daje formalnie GO, ale to ta sama historia: dodatnio, tylko ledwo.

**Retest hipotez z R5** (zapisanych przed tymi danymi):

| wariant | IS | forward (prov) | deny / allow | werdykt |
|---|---|---|---|---|
| default (1h/4h/1d, pivot 5) | +$2507 | +$469 | $469 / $909 | GO* |
| **4×TF** (jedyny dodatni OOS w R5) | +$676 | **−$440** | −$440 / $0 | **NO-GO** |
| pivot 3 | +$1658 | +$268 | $268 / $277 | GO* |
| **pivot 4** | **+$3234** | **+$862** | $862 / $1311 | GO* |
| 4×TF + pivot 3 / 4 | −$184 / +$1426 | +$387 / +$530 | | GO* (orient.) |
| strefa (0.705, 0.79) | +$3159 | +$318 | $318 / $538 | GO* |

Wnioski: (1) wskazówka „4×TF jest robustniejsze" z R5 **nie przeżyła**, bo 7 trade'ów OOS to był szum. Dobrze,
że zakaz optymalizacji na OOS zatrzymał przestawienie defaultu. (2) **Pivot 4** jest lepszy od 5 i na IS,
i na forward, i to w obu widełkach. To pierwszy kandydat na zmianę defaultu, który przeszedł dwa niezależne okna.
Mimo to decyzja należy do Kuby, a próba to 23 trade'y. (3) Strefa OTE na forward traci efektywność (exp $8/tr).

---

### R7 — dane do 13.11, forward przedłużony (15.11) → **NO-GO**
Świeży eksport (`tvexport.mjs`, 15m od 28.08, czyli długa nakładka z eksportem 18.10), `merge_data.py`:
**0 rozjazdów** na wszystkich TF, żadnej nowej dziury. Parametry dalej zamrożone, IS dalej $2507.29.
Okres 16.10–13.11 dał **6 trade'ów, wszystkie short i wszystkie na SL** (−6R, −$1009, 03–13.11).
Ten jeden miesiąc zabrał cały zysk z forwardu R6.

| | trades | PnL | PF | WR | exp/tr |
|---|---|---|---|---|---|
| IS 1.03–11.06 | 25 | +$2507 | 2.48 | 40% | $100 |
| Forward R6 (30.06–16.10) | 20 | +$469 | 1.34 | 30% | $23 |
| **Forward R7 (30.06–13.11)** | **26** | **−$540** | **0.77** | 23% | **−$21** |
| forward deny / allow | | −$540 / −$100 | 0.77 / 0.96 | | |

Miesiące 07 +395 / 08 −17 / 09 −479 / 10 +570 / **11 −1009**. Long 16 tr −$13, short 10 tr −$527.
**Wszystkie warianty hipotez są ujemne na forward** (pivot 4 najbliżej zera: −$78 / allow +$371).
Walk-forward 60/40 na całości: OOS −$935, PF 0.56, 21 tr. Headline całości: 51 tr, +$1967, PF 1.48.
Wniosek: przewaga z mar–kwi **nie przenosi się** na kolejne 4,5 miesiąca. Defaultów nie zmieniam.

### R8 — próba poprawy wyjść (15.11) → **nic nie przeszło kryterium**
Hipoteza z diagnozy R7: „14/20 przegranych w forward było najpierw ≥1R na plusie” → częściowe zamknięcie
albo BE na 1R powinno je uratować. Zarejestrowane przed liczeniem: H1 partial 1R + BE, H2 BE na 1R,
H3 `TP_MAX_R` 2.5, H4 pivot 4 + najlepszy z H1–H3.

**Diagnoza była błędna — artefakt pomiaru.** 12 z 14 takich trade'ów „było na +1R” wyłącznie na
**barze wejścia, zanim limit się wypełnił** (cena była wysoko, zjechała do 0.79, wypełniła się i
poszła na SL). Silnik wliczał ekstremum całego bara wejścia do MFE. Poprawka w `_manage`: MFE z bara
wejścia tylko przy fillu na open (PnL bez zmian, tylko statystyka). Po poprawce: na +1R przed stratą
było 6/20 przegranych w forward i 3/15 w IS. **Problemem są wejścia, nie wyjścia** — przegrane idą
prosto na SL.

| wariant | IS | forward deny / allow | PF fwd | mies.+ | WF OOS (60/40) |
|---|---|---|---|---|---|
| default | +$2507 | −$540 / −$100 | 0.77 | 2/5 | −$935 |
| H1 partial 1R | +$1699 | −$605 / +$456 | 0.69 | 2/5 | — |
| H2 BE 1R | +$2107 | −$405 / +$35 | 0.79 | 2/5 | −$887 |
| H3 TP_MAX_R 2.5 | +$1859 | −$739 / +$43 | 0.68 | 2/5 | — |
| pivot 4 (R6) | +$3234 | −$78 / +$371 | 0.97 | 2/5 | +$26 |
| **H4 pivot 4 + BE 1R** | **+$2816** | **+$131 / +$580** | 1.07 | **1/5** | **+$148** |

H4 jest jedynym wariantem dodatnim na forward w obu widełkach i jedynym z dodatnim WF OOS, ale
1/5 miesięcy dodatnich (gorzej niż default) → **nie przechodzi kryterium stabilności**. Kandydat do
decyzji Kuby, default NIE zmieniony. Uwaga: forward 30.06–13.11 jest już „widziany” (wybieraliśmy na nim
spośród 4 hipotez) — prawdziwy test każdego wyboru to dane od 14.11.

## 4. Cmentarz pomysłów — sprawdzone i ODRZUCONE przez dane

**Nie wracaj do tego bez nowych danych.** Każda z tych rzeczy brzmiała sensownie i każda została
zmierzona:

| Pomysł | Wynik | Dlaczego odrzucony |
|---|---|---|
| `BOS_DISPLACEMENT` (BOS tylko gdy świeca ma momentum ≥1.5 ATR) | **−$502, PF 0.34** | Odsiewał też prawdziwe złamania. Toggle został do badań, default OFF, **nie wniesiony do Pine** |
| Filtr confluence `"sweep"` (wymagaj sweepa płynności przed wejściem) | **−$716** | Za ciasny — wycinał dobre wejścia |
| `MAX_HOLD_BARS`, `EXIT_ON_SESSION_END`, `TRAIL_TO_SWING` | gorzej w każdej wersji | **Cięły runnery.** Cały zysk tej strategii siedzi w kilku dużych trade'ach — wyjście czasowe je zabija |
| `ENTRY_FILTER_MODE="none"` (bez filtra FVG/NWOG/key open) | 76 tr, ale deny gorszy | Więcej próbki, ale wraca niejednoznaczność intrabar i spada jakość |
| `BIAS_METHOD="HH/HL"` na 4 TF | **0 trade'ów** | Wymóg HH+HL jednocześnie na czterech TF praktycznie nigdy nie zachodzi |
| Bufory SL 1.05 / 1.1 nogi | gorzej | — |
| TP na 0.5 / 0.0 nogi | gorzej | — |
| Break-even na 0.5 nogi | gorzej | Wyrzucał z trade'ów, które potem dochodziły do TP |
| `EXIT_MODE="fib"` (stare wyjścia) | +$1401 vs +$2067 | Zastąpione przez liquidity |
| R8 `PARTIAL_R=1.0` (pół pozycji na +1R, reszta BE) | IS +$1699, fwd **−$605** | Diagnoza stała na artefakcie MFE (patrz R8). Ucina runnery, a przegrane i tak idą prosto na SL |
| R8 `TP_MAX_R=2.5` (bliższy target) | IS +$1859, fwd **−$739** | Ucina runnery, które niosą cały zysk |
| R8 `BE_AT_R=1.0` (sam BE na +1R) | IS +$2107, fwd −$405 | Lekko lepiej na forward, gorzej na IS — nie przechodzi kryterium |

Dwie rzeczy **nie** są na tej liście, choć wyglądają podobnie — bo są tylko odłożone, nie odrzucone:
**strefa OTE `(0.705, 0.79)`** (przechodzi kryterium, ale to kompromis PF/DD — decyzja Kuby: default
zostaje pojedynczy) i **`BIAS_TFS` = 4×TF** (odrzucone na train, ale **jedyne dodatnie OOS** — patrz niżej).

---

## 5. Werdykt: dlaczego Monte Carlo mówiło „tak", a walk-forward „nie"

To jest najważniejszy wniosek metodologiczny całego projektu.

**`validate_mc.py` (Monte Carlo)** mówi bardzo ładnie: 95% serii dodatnich, mediana +$2435,
maxDD p95 $942 / p99 $1132, ryzyko ruiny ~0% dla konta ≥$2000 (3% dla $1000). Problem: bootstrap
**resampluje w kółko te same 25 trade'ów**. Odpowiada więc na pytanie „jak mogłyby się poukładać
te wyniki", a nie „czy strategia zadziała na nowych danych". Jest **okrężny**.

**`validate_wf.py` (walk-forward)** odpowiada na to drugie pytanie — i odpowiada **NO-GO**.

Do tego doszedł **podpis przeuczenia**: to, co optymalizacja in-sample odrzuciła, okazało się
robustniejsze poza próbką.

- `BIAS_TFS` = **4×TF** (15m+1h+4h+1d), odrzucone w R2 → **jedyny wariant dodatni OOS**: +$203, PF 1.33 — **na forward R6 nie przeżyło (−$440)**
  (default (1h,4h,1d) dał −$82)
- `PIVOT_LEN` **3 i 4** → OOS +$527 i +$513, podczas gdy default **5 jest jedyną wartością ujemną**
- proxy overfittingu wyboru: **60%** (najlepsza-na-train utrzymuje się ≥ mediany OOS tylko w 2/5 parametrów)

Uczciwie: **OOS to 7–10 trade'ów**. To brama go/no-go — ujawnia kruchość — a **nie dowód**.
Dowodem będzie dopiero większa próbka albo forward-test.

---

## 6. Decyzje Kuby (nie moje — do uszanowania)

1. **Kryterium akceptacji zmiany defaultu**: wariant musi być **dodatni w OBU widełkach (deny i allow)**
   i **stabilny między miesiącami**. Nigdy „bo ma najwyższy PF" na ~25 trade'ach.
2. **`RISK_PER_TRADE_USD = $100`** — świadomie zrównoważony punkt na krzywej zysk/obsunięcie,
   nie maksymalny.
3. **`ENTRY_FIBS = (0.79,)`** zostaje defaultem; strefa `(0.705, 0.79)` jest udokumentowaną opcją.
4. **Zakaz optymalizacji na zbiorze OOS.** Po R5 wiadomo, że 4×TF i pivot 3–4 wypadły tam lepiej —
   i właśnie dlatego **nie wolno** ich teraz ustawić jako default. To byłby ten sam błąd od drugiej strony.
   Zostają jako **wskazówka do retestu**, gdy pojawi się więcej danych.
5. Poprawki **poprawności pomiaru** (tryb „provable", gap-guard, wycena stopów po luce) wchodziły od razu,
   bez pytania — bo to nie jest tuning strategii, tylko naprawa miary.

---

## 7. Lekcje techniczne

**Dane z TradingView.** TV oddaje maksymalnie ~3,3 miesiąca świec 15-minutowych (1H od 05.2025,
4H od 2023, 1D od 2019). To jest twarde ograniczenie całego projektu. Eksport: przewijanie wykresu
w tył przez `timeScale().zoomToBarsRange(firstIndex-2000, ...)` z **ujemnym indeksem** doładowuje
historię (w pętli, aż przestanie przybywać), potem pobranie przez **Blob download** — `fetch` na
localhost blokuje CSP. Przez MCP się nie da: `data_get_ohlcv` ma limit 500 barów na wywołanie
i nie potrafi zrzucić do pliku (dlatego walidacja krzyżowa na MES stoi).

**Niedzielne luki.** Jeśli stop księgować po cenie SL, luka przez cały leg produkuje fantomowy zysk.
Silnik wycenia stopy po `max(SL, open)` / `min(SL, open)`, a `GAP_GUARD` w ogóle nie otwiera pozycji,
której fill leży już za stopem.

**Widełki deny/allow.** Świeca 15m nie mówi, co było pierwsze w barze — TP czy SL. `deny` liczy zawsze
na niekorzyść, `allow` zawsze na korzyść, `provable` przyznaje tylko to, co da się udowodnić. Prawda
leży między deny a allow; **patrz na deny**. Od R2 obie są sklejone, bo wyjścia płynnościowe usunęły
sporne przypadki — gdyby kiedyś się rozjechały, to sygnał, że zmiana wprowadziła niejednoznaczność.

**`BIAS_AT`.** Odczyt biasu „na zamknięciu poprzedniej świecy" (moment uzbrojenia limitu) daje 20
trade'ów; odczyt „w momencie wejścia" daje 4 — przy 79% retracementu cena zdążyła przejść na drugą
stronę EMA20 15m. Semantyka `[1]` + lookahead w `HtfStruct`/`HtfEma` odwzorowuje to, co realnie widzi
się na wykresie.

**Analiza poboczna: Midnight Open 8:30** (`backtest/midnight_open_830.py`, 05.08.2026, niezwiązana
ze strategią Fib). Fade linii 0:00 ET przy dotknięciu w świecy 08:30. Okazało się, że cena dociera
do MO o tej porze tylko **11 dni na 74 (15%)** — zwykle jest wtedy ~72 pkt od niej. Na tych 11
trade'ach fade RR 4:1 był dodatni (deny +$171 / PF 2.16, allow +$472 / PF 6.62), **ale**: 9 z 11
to longi w byczym okresie marzec–czerwiec, więc edge może być po prostu trendowy, a 15m to proxy
zamiast właściwych ≤5 min. Orientacyjne, nie do handlu.

---

## 8. Co dalej

Kolejność nie jest dowolna — **wdrożenie i MES dopiero po większej próbce**:

1. **#1 więcej danych 15m** — R6+R7: 51 tr łącznie, ostatni eksport 15.11 → następny najpóźniej ~15.01.2027. TV daje ~5000 barów 15m wstecz, więc **eksport co ≤2 mies.**, inaczej powstają dziury. Dłuższa historia nadal tylko z Tradovate/IBKR.
   Źródła: Tradovate historical API albo IBKR.
2. **#3 forward-test na papierze** — Tradovate demo, z `backtest/engine.py` użytym jako biblioteka
   sygnałów (Opcja B w `AUTOMATION.md`). Jedyny sposób na rozstrzygnięcie widełek intrabar naprawdę.
3. **MES jako walidacja krzyżowa** — `--instrument mes` gotowe w kodzie, brakuje wyeksportowanych
   `data/mes_*.csv` (handoff: eksport z TV metodą jak dla MNQ).

Przy retestcie na większej próbce sprawdzić w pierwszej kolejności: **`BIAS_TFS` = 4×TF + `PIVOT_LEN` 3–4.**

Drogi do robota (pełny opis w `AUTOMATION.md`): **A** — alerty z Pine → webhook → executor;
**B** — bot czytający `engine.py` jako bibliotekę sygnałów, na API brokera; **C** — pełna implementacja
od zera. Rekomendacja: **B**, bo nie duplikuje logiki.

---

## 9. Powiązania

- **Indykator Pine** „ICT Setup — NQ All-In-One" (`pine/ict_setup_nq_all_in_one.pine`) — źródło logiki
  i parytet 1:1. Zmiana reguły tutaj wymaga zmiany tam. Uwaga: skrypt ma **limit 32 KB przy zapisie**
  na TradingView, więc każdy nowy moduł wymaga usunięcia czegoś innego.
