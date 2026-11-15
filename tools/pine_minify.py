#!/usr/bin/env python3
"""Build a compact copy of a Pine script for uploading to TradingView.

TradingView's pine-facade sits behind nginx with a ~32 KB request-body limit; a larger
script is rejected with HTTP 413 and the save silently fails in the UI. The readable,
fully commented file stays the source of truth — this strips what only humans need:
full-line comments, blank lines, trailing comments and column-alignment padding.

Strings are respected, so `//` and runs of spaces inside tooltips survive untouched.
`//@version` / `//@description` annotations are kept — Pine needs them.

    python3 pine_minify.py <source.pine> <out.pine>
"""
import sys


def _scan(line, collapse):
    """Walk a line outside/inside string literals; drop `//` comments, optionally
    collapse repeated spaces. Returns the rewritten line."""
    indent = len(line) - len(line.lstrip(" "))
    out, i, in_str, quote = [], indent, False, ""
    while i < len(line):
        ch = line[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):      # escape: copy the pair verbatim
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                in_str = False
        elif ch in "\"'":
            in_str, quote = True, ch
            out.append(ch)
        elif ch == "/" and line[i + 1:i + 2] == "/":
            break                                      # trailing comment
        elif collapse and ch == " " and out and out[-1] == " ":
            pass                                       # alignment padding
        else:
            out.append(ch)
        i += 1
    return " " * indent + "".join(out).rstrip()


def minify(src):
    """Blank lines are KEPT (collapsed to one). They cost ~150 bytes in total and keep
    the uploaded code close to the readable original, which makes diffing the two sane.
    (They were once blamed for a CE10156 "Syntax error at input rb_wick_min" — that was
    actually Monaco auto-indenting the pasted text, see pine_commit.js.)"""
    kept = []
    for line in src.split("\n"):
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":                # collapse runs of blank lines
                kept.append("")
            continue
        if stripped.startswith("//"):
            if stripped.startswith("//@"):             # compiler annotation, must stay
                kept.append(stripped)
            elif kept and kept[-1] != "":              # a comment separated blocks — keep the gap
                kept.append("")
            continue
        line = _scan(line, collapse=True)
        if line.strip():
            kept.append(line)
    while kept and kept[-1] == "":
        kept.pop()
    return "\n".join(kept) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src = open(sys.argv[1], encoding="utf-8").read()
    out = minify(src)
    open(sys.argv[2], "w", encoding="utf-8").write(out)
    before, after = len(src.encode()), len(out.encode())
    print(f"{sys.argv[1]} {before} B -> {sys.argv[2]} {after} B "
          f"(-{before - after} B, {after * 100 // 32768}% of the ~32 KB upload limit)")
