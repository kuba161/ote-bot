#!/bin/zsh
# ote_bot — dwuklik i gotowe: przelicza backtest i otwiera dashboard.
#
# To okno Terminala JEST serwerem: Ctrl+C albo zamknięcie okna kończy pracę.
# Instrukcja i rozwiązywanie problemów: README.md obok tego pliku.

# Ścieżka liczona z położenia skryptu, nie zaszyta na sztywno — dzięki temu ten sam
# plik działa niezależnie od tego, gdzie leży katalog.
HERE="${0:A:h}"
cd "$HERE" || exit 1

PORT=8420
URL="http://localhost:$PORT"

# Własny venv, jeśli jest; inaczej systemowy python3. Kod jest stdlib only,
# więc oba liczą to samo — venv trzyma tylko pytest.
PY="$HERE/venv/bin/python"
[ -x "$PY" ] || PY="python3"

if ! command -v "$PY" >/dev/null 2>&1 && [ ! -x "$PY" ]; then
    echo "  BŁĄD: nie ma python3 w systemie.  Instalacja: brew install python3"
    read -k 1 -s "?  Naciśnij dowolny klawisz..."
    exit 1
fi

echo ""
echo "  ══════ ote_bot — backtest Fib OTE na MNQ ══════"
echo ""
echo "  Liczę backtest (chwilę to trwa)..."
echo ""

if ! "$PY" backtest/run_backtest.py; then
    echo ""
    echo "  Backtest się nie policzył. Dashboard pokaże stare wyniki z site/results.json."
    echo "  Najczęstsza przyczyna: brak plików w data/ (patrz data/README.md)."
    echo ""
    read -k 1 -s "?  Naciśnij dowolny klawisz, żeby mimo to otworzyć dashboard..."
fi

# Ubij poprzedni serwer — bierzemy to, co faktycznie trzyma port, niezależnie od tego,
# jak zostało uruchomione (pkill po nazwie pliku potrafi go minąć).
lsof -ti tcp:$PORT | xargs kill 2>/dev/null

# Przeglądarka chwilę po starcie serwera.
( sleep 1; open "$URL" ) &

echo ""
echo "  ──────────────────────────────────────────────"
echo "   NIE ZAMYKAJ tego okna — dashboard działa,"
echo "   dopóki ono jest otwarte.  Ctrl+C = stop."
echo "   $URL"
echo "  ──────────────────────────────────────────────"
echo ""

# exec: serwer przejmuje proces okna, więc zamknięcie okna nie zostawia sieroty
# trzymającej port 8420.
exec python3 -m http.server "$PORT" --directory site
