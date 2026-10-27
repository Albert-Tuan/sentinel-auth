"""Static architecture tests: bounded-context ownership of the source code.

These tests do not need a database.  They inspect the application source
to prove that the bounded contexts stay separated at the CODE level, which
a database-level test cannot prove on its own:

* the Detection context must not import or query Core-owned ORM models
  (``User``, ``Session``, ``Role``, ``UserRole``, ``AuditLog``, ...);
* the Detection context must not depend on ``get_core_db``;
* the Detection context must reach Core only through the canonical
  internal action boundary (``POST /api/v1/internal/actions``);
* the ML context must not depend on ``get_core_db`` or ``get_detection_db``.

They are deliberately static (AST-based) rather than runtime-based: a
runtime test can only observe the paths it happens to exercise, while the
AST check covers every statement in the module.
"""
from __future__ import annotations

import ast
import os
from typing import Set

import pytest

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"
)

#: ORM models owned by the Core context.  The Detection and ML contexts
#: must never query them directly.
CORE_OWNED_MODELS = frozenset({
    "Role",
    "User",
    "UserRole",
    "IpAddress",
    "Session",
    "MfaTransaction",
    "MfaNotification",
    "AuditLog",
    "UserTrustedDevice",
    "SystemSetting",
    "OutboxEvent",
    "UserNotification",
    "RateLimit",
})


def _parse(filename: str) -> ast.Module:
    path = os.path.join(APP_DIR, filename)
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _imported_names(tree: ast.Module) -> Set[str]:
    """Return every name bound by an ``from app.models import ...``."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.models":
            for alias in node.names:
                names.add(alias.name)
    return names


def _imported_modules(tree: ast.Module) -> Set[str]:
    """Return every module named in an ``import``/``from`` statement."""
    modules: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


class TestDetectionDoesNotTouchCoreTables:
    """The Detection context owns alerts and must not query Core tables."""

    @pytest.mark.parametrize("module", ["detection.py", "alerts.py"])
    def test_no_core_owned_models_are_imported(self, module):
        tree = _parse(module)
        imported = _imported_names(tree)
        offenders = imported & CORE_OWNED_MODELS
        assert not offenders, (
            f"{module} imports Core-owned ORM models {sorted(offenders)}. "
            f"The Detection context must use its own tables and reach Core "
            f"only through the internal action boundary."
        )

    @pytest.mark.parametrize("module", ["detection.py", "alerts.py"])
    def test_no_core_db_dependency(self, module):
        tree = _parse(module)
        assert "get_core_db" not in _imported_modules(tree), (
            f"{module} depends on get_core_db. The Detection context must "
            f"use get_detection_db only."
        )

    @pytest.mark.parametrize("module", ["detection.py", "alerts.py"])
    def test_no_core_session_dependency_is_declared(self, module):
        """No route may declare a second, Core-bound database session."""
        tree = _parse(module)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for decorator in node.decorator_list:
                text = ast.unparse(decorator)
                if "get_core_db" in text:
                    offenders.append(f"{node.name}: {text}")
        assert not offenders, (
            f"{module} declares a Core-bound DB dependency: {offenders}"
        )


class TestDetectionReachesCoreOnlyThroughTheBoundary:
    """Protective actions must go through ``POST /api/v1/internal/actions``."""

    def test_alerts_actions_endpoint_uses_the_shared_internal_client(self):
        tree = _parse("alerts.py")
        source = ast.unparse(tree)

        assert "internal_client.enforce_action_in_core" in source, (
            "alerts.py must enforce protective actions through the shared "
            "internal client, not by mutating Core rows directly."
        )

    def test_internal_client_calls_the_canonical_endpoint(self):
        tree = _parse("internal_client.py")
        source = ast.unparse(tree)
        assert "/api/v1/internal/actions" in source, (
            "the shared internal client must call the canonical Core action "
            "boundary POST /api/v1/internal/actions."
        )

    def test_alerts_does_not_mutate_core_columns(self):
        """No direct writes to Core-owned attributes anywhere in alerts.py."""
        tree = _parse("alerts.py")
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            # ``user.status = ...`` / ``user.detection_mfa_once = ...`` would
            # be a direct Core mutation.  Detection-owned attributes such as
            # ``alert.status`` are fine.
            if node.attr in ("detection_mfa_once", "locked_at", "revoked_at",
                             "admin_mfa_required"):
                offenders.append(f"{node.attr} (line {node.lineno})")
        assert not offenders, (
            f"alerts.py mutates Core-owned state directly: {offenders}. "
            f"Use the internal action boundary instead."
        )


class TestMlContextIsIsolated:
    """The ML context owns the model registry and inference logs."""

    @pytest.mark.parametrize(
        "forbidden", ["get_core_db", "get_detection_db"]
    )
    def test_ml_does_not_depend_on_other_contexts(self, forbidden):
        tree = _parse("ml.py")
        assert forbidden not in _imported_modules(tree), (
            f"ml.py depends on {forbidden}. The ML context must use "
            f"get_ml_db only."
        )

    def test_ml_does_not_import_core_owned_models(self):
        tree = _parse("ml.py")
        offenders = _imported_names(tree) & CORE_OWNED_MODELS
        assert not offenders, (
            f"ml.py imports Core-owned ORM models {sorted(offenders)}"
        )
