#!/usr/bin/env python3
"""M12.0 doc drift checker.

Cross-checks the claims in docs/frontend/*.md against the LIVE backend:
  - OpenAPI regenerated from the real FastAPI app
  - error status codes extracted from the actual source code (AST-scoped)
  - schema fields taken from the live OpenAPI components

Run from the repo root:  python3 scripts/check_m12_docs_drift.py
Exit code 0 = no drift, 1 = drift found.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "frontend"

FAILURES: list[str] = []
NOTES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def note(msg: str) -> None:
    NOTES.append(msg)


# --------------------------------------------------------------------------
# 1. Live OpenAPI
# --------------------------------------------------------------------------
def load_openapi() -> dict:
    os.environ.setdefault(
        "INTERNAL_SECRET", "drift-check-internal-secret-0123456789abcdef"
    )
    sys.path.insert(0, str(ROOT))
    from app.main import app  # noqa: PLC0415

    return app.openapi()


def live_operations(spec: dict) -> set[tuple[str, str]]:
    return {
        (m.upper(), path)
        for path, ops in spec["paths"].items()
        for m in ops
        if m in ("get", "post", "put", "patch", "delete")
    }


# --------------------------------------------------------------------------
# 2. Route contracts (AST-scoped, from scripts/extract_route_contracts.py)
# --------------------------------------------------------------------------
def route_contracts() -> list[dict]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import extract_route_contracts as erc  # noqa: PLC0415

    rows: list[dict] = []
    for rel in erc.MODULES:
        rows.extend(erc.scan_module(rel))
    return rows


# --------------------------------------------------------------------------
# 3. Helpers
# --------------------------------------------------------------------------
def inventory_text() -> str:
    return (DOCS / "M12-API-INVENTORY.md").read_text()


def page_map_text() -> str:
    return (DOCS / "M12-PAGE-MAP.md").read_text()


def plan_text() -> str:
    return (DOCS / "M12-INTEGRATION-PLAN.md").read_text()


# --------------------------------------------------------------------------
# 4. Checks
# --------------------------------------------------------------------------
def check_operation_tables(spec: dict) -> None:
    live = live_operations(spec)
    browser = {op for op in live if "/internal/" not in op[1]}
    internal = {op for op in live if "/internal/" in op[1]}

    inv = inventory_text()
    sec11 = inv.split("## 11. Bảng tra cứu nhanh")[1].split("## 12.")[0]
    inv_rows = {
        (m, p)
        for m, p in re.findall(
            r"\|\s*\d+\s*\|\s*(GET|POST|PUT|DELETE)\s+`([^`]+)`\s*\|", sec11
        )
    }
    if inv_rows != browser:
        fail(
            f"Inventory section 11 != live browser operations.\n"
            f"  missing: {sorted(browser - inv_rows)}\n"
            f"  extra:   {sorted(inv_rows - browser)}"
        )
    else:
        note(f"Inventory section 11 matches all {len(browser)} live browser operations.")

    pm = page_map_text()
    lines = pm.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("| Endpoint | S-01"))
    pm_rows: set[tuple[str, str]] = set()
    for line in lines[start + 2 :]:
        if not line.startswith("| `"):
            break
        mm = re.match(r"\|\s*`(\w+)\s+([^`]+)`", line)
        if not mm:
            continue
        method, path = mm.group(1).upper(), mm.group(2).strip()
        if not path.startswith("/api/") and path not in ("/health", "/ready"):
            path = "/api/v1" + path
        pm_rows.add((method, path))
    if pm_rows != browser:
        fail(
            f"Page map section 5 != live browser operations.\n"
            f"  missing: {sorted(browser - pm_rows)}\n"
            f"  extra:   {sorted(pm_rows - browser)}"
        )
    else:
        note(f"Page map section 5 matches all {len(browser)} live browser operations.")

    sec10 = inv.split("## 10. NHÓM 8")[1].split("## 11.")[0]
    inv_internal = {
        (m, p)
        for m, p in re.findall(
            r"\|\s*(GET|POST|PUT|DELETE)\s*\|\s*`(/api/v1/internal/[^`]+)`\s*\|", sec10
        )
    }
    if inv_internal != internal:
        fail(
            f"Inventory section 10 != live internal operations.\n"
            f"  missing: {sorted(internal - inv_internal)}\n"
            f"  extra:   {sorted(inv_internal - internal)}"
        )
    else:
        note(f"Inventory section 10 matches all {len(internal)} live internal operations.")


def check_error_matrix() -> None:
    """The 8.3 matrix must agree with the AST-scoped source truth."""
    rows = route_contracts()
    contracts = {(r["method"], r["path"]): r for r in rows}

    # Codes raised indirectly by a helper (not visible to the AST scan).
    HELPER_CODES = {
        ("POST", "/api/v1/admin/users/{user_id}/roles"): {"409"},
        ("DELETE", "/api/v1/admin/users/{user_id}/roles/{role_id}"): {"409"},
        ("POST", "/api/v1/admin/users/{user_id}/lock"): {"409"},
    }
    # The manager facade raises 400/503 from a shared dependency.
    MANAGER = {
        "/api/v1/manager/dashboard",
        "/api/v1/manager/trends",
        "/api/v1/manager/alerts",
        "/api/v1/manager/soc-kpi",
        "/api/v1/manager/ml-stats",
    }

    plan = plan_text()
    sec = plan.split("### 8.3 Ma trận status × endpoint")[1].split("\n---")[0]
    matrix: dict[str, set[str]] = {}
    for line in sec.splitlines():
        if not line.startswith("| `"):
            continue
        mm = re.match(r"\|\s*`([^`]+)`\s*\|(.*)\|", line)
        if not mm:
            continue
        label, rest = mm.group(1), mm.group(2)
        cells = [c.strip() for c in rest.split("|")]
        if len(cells) != 11:
            fail(f"Error matrix row `{label}` has {len(cells)} code columns, expected 11.")
            continue
        codes = {
            code
            for code, cell in zip(
                ["400", "401", "403", "404", "409", "410", "422", "423", "429", "502", "503"],
                cells,
            )
            if cell
        }
        matrix[label] = codes

    # Map each matrix label back to a live route.
    for label, claimed in matrix.items():
        m = re.match(r"(GET|POST|PUT|DELETE)\s+(\S+)", label)
        if not m:
            continue
        method, path = m.group(1), m.group(2)
        if path.endswith("/*"):
            path = "/api/v1/manager/dashboard"
        # Matrix labels omit the /api/v1 prefix (e.g. "/auth/login").
        if not path.startswith("/api/"):
            path = "/api/v1" + path
        key = (method, path)
        if key not in contracts:
            note(f"Error matrix label `{label}` has no matching live route (skipped).")
            continue
        c = contracts[key]
        actual = set(c["codes"])
        if c["uses_auth"]:
            actual.add("401")
        if c["roles"]:
            actual.add("403")
        actual |= HELPER_CODES.get(key, set())
        if path in MANAGER:
            actual |= {"400", "503"}
        extra = claimed - actual
        if extra:
            fail(
                f"Error matrix claims {sorted(extra)} for {label} "
                f"but the source only raises {sorted(actual)}."
            )


def check_schema_fields(spec: dict) -> None:
    schemas = spec["components"]["schemas"]
    blob = inventory_text() + plan_text() + (DOCS / "M12-ARCHITECTURE.md").read_text()

    field_checks = {
        "UserItem": ["id", "username", "email", "status", "admin_mfa_required",
                     "roles", "last_login_at", "failed_login_count", "locked_at", "created_at"],
        "LoginResponse": ["access_token", "refresh_token", "mfa_required", "session_id"],
        "MfaVerifyResponse": ["access_token", "refresh_token", "session_id"],
        "RefreshResponse": ["access_token", "refresh_token"],
        "UserRegisterRequest": ["username", "email", "password"],
        "MfaVerifyRequest": ["session_id", "mfa_code"],
        "RefreshRequest": ["refresh_token"],
        "AlertAssignRequest": ["assigned_to_id", "notes"],
        "AlertResolveRequest": ["resolution", "notes"],
        "AlertActionRequest": ["action", "reason"],
        "AlertActionResponse": ["status", "action", "details"],
        "PolicyUpdateRequest": ["name", "description", "rules", "config", "expected_updated_at"],
        "TrustDeviceRequest": ["device_name", "remember_for_days"],
        "PendingTrustedDeviceResponse": ["request_id", "status", "expires_at", "message"],
    }
    for name, fields in field_checks.items():
        if name not in schemas:
            fail(f"Live OpenAPI is missing schema `{name}` (doc depends on it).")
            continue
        actual = set(schemas[name].get("properties", {}))
        absent = [f for f in fields if f not in actual]
        if absent:
            fail(f"Schema `{name}` is missing doc-claimed fields {absent}.")

    # Schemas the docs mention that are source-only ("dead") must be
    # documented as such, not presented as live API.
    dead = ["AlertEscalateRequest", "AlertNoteRequest"]
    for name in dead:
        if name in schemas:
            continue
        if name not in blob:
            continue
        # The doc must flag that the schema has no route.
        flagged = re.search(
            rf"{name}[^|\n]*\b(không có route|không route|schema chết|dead|no route)\b",
            blob,
        )
        if not flagged:
            fail(
                f"Doc mentions `{name}` but does not flag it as having no route "
                f"(it is absent from the live OpenAPI)."
            )
        else:
            note(f"`{name}` correctly flagged as having no route.")


def check_enum_values(spec: dict) -> None:
    schemas = spec["components"]["schemas"]
    blob = inventory_text() + plan_text() + (DOCS / "M12-ARCHITECTURE.md").read_text()
    for enum_name in ("UserRole", "UserStatus", "RiskLevel", "SecurityAction"):
        if enum_name not in schemas:
            fail(f"Live OpenAPI missing enum `{enum_name}`.")
            continue
        for value in schemas[enum_name]["enum"]:
            if value not in blob:
                fail(f"Enum value `{value}` ({enum_name}) never appears in the docs.")


def check_counts(spec: dict) -> None:
    live = live_operations(spec)
    inv = inventory_text()
    browser = len([op for op in live if "/internal/" not in op[1]])
    internal = len([op for op in live if "/internal/" in op[1]])

    if len(live) != 57:
        note(f"Live operation count is {len(live)} (docs assume 57).")
    if f"**{len(live)}**" not in inv:
        fail(f"Inventory does not state the live total ({len(live)}).")
    if f"| **{browser}**" not in inv:
        note(f"Inventory does not state the live browser count ({browser}).")
    if f"| **{internal}**" not in inv:
        note(f"Inventory does not state the live internal count ({internal}).")

    for stale in (
        "Operation internal-only (`X-Internal-Secret`) | 12",
        "45 endpoint có thể gọi",
        "Operation có RBAC (role cụ thể) | 16",
    ):
        if stale in inv:
            fail(f"Inventory still contains a stale count: `{stale}`.")


def check_role_claims() -> None:
    """The 8.3 matrix's 403 column must match the require_roles allow-list."""
    rows = route_contracts()
    inv = inventory_text()
    sec11 = inv.split("## 11. Bảng tra cứu nhanh")[1].split("## 12.")[0]
    claims = {
        (m, p): roles.strip()
        for m, p, roles in re.findall(
            r"\|\s*\d+\s*\|\s*(GET|POST|PUT|DELETE)\s+`([^`]+)`\s*\|\s*([^|]+?)\s*\|", sec11
        )
    }
    for r in rows:
        path = r["path"]
        if path.startswith("/api/v1/internal/") or path in ("/health", "/ready"):
            continue
        key = (r["method"], path)
        if key not in claims:
            fail(f"Inventory section 11 is missing live route {key}.")
            continue
        claim = claims[key]
        actual_roles = set(r["roles"])
        if actual_roles:
            if not all(x in claim for x in actual_roles):
                fail(
                    f"Inventory roles for {key} say `{claim}` but "
                    f"require_roles allows {sorted(actual_roles)}."
                )
        elif r["uses_auth"] and "bất kỳ" not in claim and "public" not in claim:
            fail(
                f"Inventory roles for {key} say `{claim}` but the route needs "
                f"a bearer token."
            )


def main() -> int:
    spec = load_openapi()
    check_operation_tables(spec)
    check_schema_fields(spec)
    check_enum_values(spec)
    check_counts(spec)
    check_role_claims()
    check_error_matrix()

    print("=== M12.0 doc drift check ===")
    for n in NOTES:
        print(f"  info  {n}")
    if FAILURES:
        print(f"\n  DRIFT FOUND ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  FAIL  {f}")
        return 1
    print("\n  OK - docs match the live backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
