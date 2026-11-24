#!/usr/bin/env python3
"""Extract, per route function, the HTTP status codes it can raise.

Uses AST so that HTTPException calls are scoped to the route handler they
belong to (a naive line-based scan leaks codes across functions).

Also detects the `require_roles(...)` allow-list and the auth dependency used
by each route, so the frontend docs can be checked against real contracts.

Run:  python3 scripts/extract_route_contracts.py
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

MODULES = [
    "app/auth.py",
    "app/detection.py",
    "app/alerts.py",
    "app/devices.py",
    "app/iam.py",
    "app/login_history.py",
    "app/manager.py",
]

HTTP_METHODS = ("get", "post", "put", "delete", "patch")
HTTP_CONST = re.compile(r"HTTP_(\d{3})")


def status_of(node: ast.AST) -> str | None:
    """Best-effort literal resolution of a status_code= argument."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        m = HTTP_CONST.search(node.attr)
        if m:
            return m.group(1)
    if isinstance(node, ast.Call):
        m = HTTP_CONST.search(ast.unparse(node.func))
        if m:
            return m.group(1)
    return None


def router_prefixes(tree: ast.AST) -> dict[str, str]:
    """Map router variable name -> its URL prefix."""
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg != "prefix":
                continue
            prefix = ast.unparse(kw.value).strip("\"'")
            for t in node.targets:
                if isinstance(t, ast.Name):
                    prefixes[t.id] = prefix
    return prefixes


def collect_exceptions(node: ast.AST) -> tuple[set[str], dict[str, str]]:
    codes: set[str] = set()
    details: dict[str, str] = {}
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if "HTTPException" not in ast.unparse(sub.func):
            continue
        code: str | None = None
        det: str | None = None
        for kw in sub.keywords:
            if kw.arg == "status_code":
                code = status_of(kw.value)
            elif kw.arg == "detail":
                det = ast.unparse(kw.value)
        if code is None and sub.args:
            code = status_of(sub.args[0])
        if code is None:
            code = "4xx"
        codes.add(code)
        if det:
            details.setdefault(code, det)
    return codes, details


def collect_roles(node: ast.AST) -> list[str]:
    roles: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = ast.unparse(sub.func)
            if fn.startswith("require_roles"):
                roles = [ast.unparse(a).strip("\"'") for a in sub.args]
    return roles


def uses_auth_dependency(node: ast.AST) -> bool:
    """True when the route is wired to the bearer-token auth dependency."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and ast.unparse(sub.func) == "Depends":
            if not sub.args:
                continue
            src = ast.unparse(sub.args[0])
            if src in ("get_current_auth_context", "require_roles"):
                return True
            if src.startswith("require_roles"):
                return True
    return False


def scan_module(rel: str) -> list[dict]:
    tree = ast.parse((ROOT / rel).read_text())
    prefixes = router_prefixes(tree)
    out: list[dict] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr in HTTP_METHODS):
                continue
            owner = ast.unparse(func.value)
            prefix = prefixes.get(owner)
            if prefix is None or not dec.args:
                continue
            if not isinstance(dec.args[0], ast.Constant):
                continue
            raw_path = dec.args[0].value

            codes, details = collect_exceptions(node)
            for kw in dec.keywords:
                if kw.arg == "status_code":
                    s = status_of(kw.value)
                    if s:
                        codes.add(s)

            roles = collect_roles(node)
            out.append(
                {
                    "method": func.attr.upper(),
                    "path": prefix + raw_path,
                    "module": rel,
                    "function": node.name,
                    "codes": sorted(codes, key=lambda c: (len(c), c)),
                    "details": details,
                    "roles": roles,
                    "uses_auth": uses_auth_dependency(node),
                }
            )
    return out


def main() -> int:
    rows: list[dict] = []
    for rel in MODULES:
        rows.extend(scan_module(rel))

    rows.sort(key=lambda r: (r["path"], r["method"]))
    print(f"{len(rows)} routes\n")
    for r in rows:
        roles = (
            ",".join(r["roles"])
            if r["roles"]
            else ("bearer" if r["uses_auth"] else "public")
        )
        print(
            f"{r['method']:6} {r['path']:52} "
            f"{str(r['codes']):32} {roles}"
        )
    json.dump(rows, open("/tmp/route_contracts.json", "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
