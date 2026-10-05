"""Render the PlantUML diagrams in docs/ to PNG and SVG via a public Kroki server.

Usage:
    python3 scripts/render_diagrams.py [subdir] [--all] [--svg]

Examples:
    python3 scripts/render_diagrams.py              # docs/diagrams/*.uml -> PNG
    python3 scripts/render_diagrams.py v3.3-detect  # docs/diagrams/v3.3-detect/*.puml -> PNG
    python3 scripts/render_diagrams.py v3.3-detect --svg   # -> SVG
    python3 scripts/render_diagrams.py --all        # both dirs, both formats

Requires network access. Files whose source is unchanged are skipped, so
re-running is cheap. Use --all (or touch a .puml file) to force a re-render
after changing the renderer itself.
"""
from __future__ import annotations

import base64
import hashlib
import sys
import zlib
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KROKI = "https://kroki.io/plantuml"

#: Signature expected at the start of each rendered format.
MAGIC = {"png": b"\x89PNG", "svg": b"<svg"}


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


def render(uml: Path, out: Path, fmt: str) -> bool:
    source = uml.read_text()
    url = f"{KROKI}/{fmt}/{encode(source)}"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = httpx.get(url, timeout=60.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        print(f"  ! {uml.name} [{fmt}]: {exc}")
        return False
    if r.status_code != 200 or not r.content.lstrip().startswith(MAGIC[fmt]):
        print(f"  ! {uml.name} [{fmt}]: HTTP {r.status_code} {r.text[:200]}")
        return False
    out.write_bytes(r.content)
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"  ok {uml.name} -> {shown} ({len(r.content) // 1024} KB)")
    return True


def sources(subdir: str) -> list[Path]:
    """PlantUML sources for a docs/ subdirectory (accepts .uml and .puml)."""
    if subdir == "diagrams":
        found = sorted((ROOT / "docs" / "diagrams").glob("*.uml"))
        found += sorted((ROOT / "docs").glob("WF-*.uml"))
        return found
    return sorted((ROOT / "docs" / "diagrams" / subdir).glob("*.puml"))


def main() -> int:
    argv = sys.argv[1:]
    flags = {a for a in argv if a.startswith("--")}
    positional = [a for a in argv if not a.startswith("--")]

    if "--all" in flags:
        subdirs = ["diagrams", "v3.3-detect"]
    else:
        subdirs = [positional[0] if positional else "diagrams"]

    formats = ["png"]
    if "--svg" in flags:
        formats.append("svg")

    ok = failed = skipped = 0
    for subdir in subdirs:
        srcs = sources(subdir)
        if not srcs:
            print(f"  ? no .puml/.uml sources under docs/diagrams/{subdir}")
            continue
        print(f"\n== {subdir}: {len(srcs)} source(s) -> {', '.join(formats)} ==")
        for uml in srcs:
            for fmt in formats:
                # sources() mixes docs/diagrams/*.uml with docs/WF-*.uml, so
                # the output always belongs NEXT TO ITS SOURCE - deriving it
                # from the subdir would drop the WF-* files into a nested
                # docs/diagrams/diagrams/ directory.
                out = uml.with_suffix(f".{fmt}")
                if (
                    out.exists()
                    and out.stat().st_mtime >= uml.stat().st_mtime
                    and "--all" not in flags
                ):
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
