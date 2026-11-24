#!/usr/bin/env python3
"""
Migrate the remaining light-theme Tailwind classes to the Sentinel Telemetry
Operator tokens.

The mapping is deliberately mechanical and one-way:

    bg-white            -> bg-surface-raised
    bg-slate-100        -> bg-surface
    bg-slate-50         -> bg-panel
    border-slate-200    -> border-border
    border-slate-300    -> border-border
    text-slate-900      -> text-text
    text-slate-800      -> text-text
    text-slate-700      -> text-text
    text-slate-600      -> text-text-muted
    text-slate-500      -> text-text-muted
    text-slate-400      -> text-degraded
    text-slate-300      -> text-degraded
    text-indigo-600     -> text-secondary
    text-red-600        -> text-danger
    text-emerald-700    -> text-success
    text-amber-700      -> text-warning

`rounded-*` needs no change: the whole radius scale is collapsed to 0 in
`src/styles/index.css`.
"""

from __future__ import annotations

import pathlib
import re
import sys

FRONTEND_SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"

# Longest first, so `text-slate-500` is not shadowed by `text-slate-50`.
CLASS_MAP: list[tuple[str, str]] = [
    ("bg-white", "bg-surface-raised"),
    ("bg-slate-100", "bg-surface"),
    ("bg-slate-50", "bg-panel"),
    ("border-slate-200", "border-border"),
    ("border-slate-300", "border-border"),
    ("border-slate-400", "border-border"),
    ("text-slate-900", "text-text"),
    ("text-slate-800", "text-text"),
    ("text-slate-700", "text-text"),
    ("text-slate-600", "text-text-muted"),
    ("text-slate-500", "text-text-muted"),
    ("text-slate-400", "text-degraded"),
    ("text-slate-300", "text-degraded"),
    ("text-indigo-600", "text-secondary"),
    ("text-indigo-700", "text-secondary"),
    ("text-red-600", "text-danger"),
    ("text-emerald-700", "text-success"),
    ("text-amber-700", "text-warning"),
    ("focus:ring-indigo-200", "focus:border-primary"),
    ("focus:ring-indigo-500", "focus:border-primary"),
    ("focus:border-indigo-500", "focus:border-primary"),
    ("focus:ring-2", ""),
    ("focus:ring-red-200", ""),
    ("focus:border-red-500", "focus:border-danger"),
    ("focus:ring-red-500", ""),
    ("disabled:bg-slate-100", "disabled:bg-surface-sunken"),
    ("hover:bg-red-50", "hover:bg-danger/10"),
    ("hover:bg-red-600", "hover:bg-danger"),
    ("hover:bg-slate-50", "hover:bg-panel"),
    ("hover:bg-slate-100", "hover:bg-surface-raised"),
    ("hover:bg-indigo-50", "hover:bg-secondary/10"),
    ("hover:bg-indigo-700", "hover:bg-secondary"),
    ("hover:text-indigo-700", "hover:text-primary"),
    ("hover:text-slate-900", "hover:text-text"),
    ("hover:text-slate-700", "hover:text-text"),
    ("hover:text-slate-600", "hover:text-text-muted"),
    ("hover:text-slate-500", "hover:text-text-muted"),
    ("divide-slate-100", "divide-border"),
]


def migrate(text: str) -> str:
    for old, new in CLASS_MAP:
        if new:
            text = re.sub(rf"(?<![\w-]){re.escape(old)}(?![\w-])", new, text)
    # Drop classes that became empty (e.g. `focus:ring-2`).
    text = re.sub(r'\s+focus:ring-2(?=[\s"\'])', "", text)
    return text


def main() -> int:
    changed: list[str] = []
    for path in sorted(FRONTEND_SRC.rglob("*.tsx")):
        original = path.read_text(encoding="utf-8")
        updated = migrate(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path.relative_to(FRONTEND_SRC)))

    for item in changed:
        print(item)
    print(f"{len(changed)} file(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
