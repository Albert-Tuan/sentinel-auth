"""Render the PlantUML diagrams in docs/ to PNG via a public Kroki server.

Usage:  python3 scripts/render_diagrams.py [output-subdir]
Requires network access. Files whose .uml is unchanged are skipped, so
re-running is cheap.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import zlib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KROKI = "https://kroki.io/plantuml/png"


def encode(source: str) -> str:
    """PlantUML's own deflate + custom base64 (as used by the public servers)."""
    alphabet = (
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
    )
    data = zlib.compress(source.encode("utf-8"), 9)
    # strip zlib header/checksum, keep the raw deflate stream
    data = data[2:-4]

    def b64encode(data: bytes) -> str:
        out = []
        for i in range(0, len(data), 3):
            chunk = data[i: i + 3]
            b = int.from_bytes(chunk + b"\x00" * (3 - len(chunk)), "big")
            out.append(alphabet[(b >> 18) & 0x3F])
            out.append(alphabet[(b >> 12) & 0x3F])
            if len(chunk) > 1:
                out.append(alphabet[(b >> 6) & 0x3F])
            if len(chunk) > 2:
                out.append(alphabet[b & 0x3F])
        return "".join(out)

    return b64encode(data)


def render(uml: Path, out: Path) -> bool:
    source = uml.read_text()
    url = f"{KROKI}/{encode(source)}"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.get(url, timeout=60.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        print(f"  ! {uml.name}: {exc}")
        return False
    if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
        print(f"  ! {uml.name}: HTTP {r.status_code} {r.text[:120]}")
        return False
    out.write_bytes(r.content)
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"  ok {uml.name} -> {shown} ({len(r.content) // 1024} KB)")
    return True


def main() -> int:
    outdir = ROOT / "docs" / (sys.argv[1] if len(sys.argv) > 1 else "diagrams")

    sources: list[Path] = sorted((ROOT / "docs" / "diagrams").glob("*.uml"))
    sources += sorted((ROOT / "docs").glob("WF-*.uml"))

    ok = failed = skipped = 0
    for uml in sources:
        out = outdir / (uml.stem + ".png")
        if out.exists() and out.stat().st_mtime >= uml.stat().st_mtime:
            skipped += 1
            continue
        if render(uml, out):
            ok += 1
        else:
            failed += 1

    print(f"\n{ok} rendered, {skipped} unchanged, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
