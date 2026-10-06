#!/usr/bin/env python3
"""Render the report diagrams in docs/bao-cao/ to PNG via the public Kroki server.

Usage:
    python3 scripts/render_bao_cao.py [--svg] [--all]

Reuses scripts/render_diagrams.py for encoding and transport. Skips files whose
PNG is newer than the source unless --all is given.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_diagrams import ROOT, render  # noqa: E402

SRC = ROOT / "docs" / "bao-cao"


def main() -> int:
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    formats = ["png"] + (["svg"] if "--svg" in flags else [])

    srcs = sorted(SRC.glob("*.puml")) + sorted(SRC.glob("*.uml"))
    if not srcs:
        print(f"  ? no sources under {SRC.relative_to(ROOT)}")
        return 1

    print(f"\n== bao-cao: {len(srcs)} source(s) -> {', '.join(formats)} ==")
    ok = failed = skipped = 0
    for uml in srcs:
        for fmt in formats:
            out = uml.with_suffix(f".{fmt}")
            if out.exists() and out.stat().st_mtime >= uml.stat().st_mtime and "--all" not in flags:
                skipped += 1
                continue
            if render(uml, out, fmt):
                ok += 1
            else:
                failed += 1

    print(f"\n{ok} rendered, {skipped} unchanged, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
