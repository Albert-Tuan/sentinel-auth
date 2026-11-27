#!/usr/bin/env python
"""Sentinel Auth v3.3 — the demo-database guard of the M13.2 E2E fixtures.

``scripts/e2e_fixtures.py`` WRITES rows (the alerts, the policies, the
sessions, the MFA gate, the rate-limit counters) and DELETES rows (the
alerts, the policies).  It is the ONLY thing in the browser suite that
writes to a database directly, so it is also the only place where a
mistake could reach a database that must never be touched.

This module is that place's guard.  It answers one question, in one
place, for all three bounded contexts:

    *is this URL a database the E2E suite is allowed to mutate?*

===========================================================================
THE SAFETY MODEL — FAIL-CLOSED, LAYER BY LAYER
===========================================================================

Every layer below REFUSES by default.  The destructive SQL runs only when
ALL of them are satisfied.  The layers are independent, so a bug in one
does not open a hole in the next.

    Layer 1  CONTEXT MATCH   The database name must be one of the two
                             names the CONTEXT owns, and the URL must
                             point at the CONTEXT's own URL variable.  A
                             core URL cannot reach the detection
                             database, and a detection URL cannot reach
                             the core database.

    Layer 2  NAME ALLOWLIST  The name must be EXACTLY one of the four
                             known demo names - the local demo stack's
                             ``*_demo`` names and the CI disposable
                             ``*_ci_demo`` names.  A suffix check alone
                             is not enough: ``sentinel_core_demo_prod``
                             would pass a ``_demo`` suffix check, and it
                             would be a production database.

    Layer 3  NO OVERLAP      The regression suite's ``*_test`` databases
                             and the canonical production databases are
                             refused outright.  They are not "demo
                             databases that happen to be named oddly" -
                             they are a different vocabulary with a
                             different owner.

    Layer 4  LOOPBACK HOST   The server must be on the loopback
                             interface.  A demo database that lives on
                             another host is a shared database, and a
                             shared database is not the suite's to
                             mutate.

    Layer 5  EXPLICIT OPT-IN The run must have declared that it is
                             allowed to write.  The declaration names
                             the EXACT database the helper is about to
                             touch, so it cannot be carried over from
                             another target.

NO SINGLE ENVIRONMENT VARIABLE CAN DISABLE THE PROTECTION.  Layers 1 to 4
are decided by the URL alone, and the allowlists are hard-coded: no
environment variable can widen them.  Layer 5 is a separate input, and it
must name the very database the helper is about to write to - so a
declaration that was made for one target cannot authorise another.

The declaration follows the convention of
``scripts/ci_bootstrap_demo_databases.sh``: it is a space-separated list
of database NAMES, and it is checked against the target the helper
resolved.  A generic "true" authorises nothing, and a declaration made
for one database cannot carry over to another.

===========================================================================
THE ONE DELIBERATE EXCEPTION
===========================================================================

``restore-active-policy`` restores the demo stack's SEEDED active policy.

Every other operation in this helper touches ONLY rows the E2E suite
created: the ids carry the ``m13-e2e-`` marker, and the helper refuses
to write to a row that does not carry it.  Restoring the seeded active
policy is the one operation that deliberately touches a row the suite did
NOT create, and it is a legitimate exception to the "E2E-owned rows
only" rule.

It is legitimate because it is the RESTORE of a state the behaviour under
test changed: activating a policy deactivates the current one - that is
the product behaviour, and the browser scenario has to prove it.  The
side effect is that the seeded ACTIVE policy of the demo stack is no
longer active, so the demo would drift away from its own fixtures.
Putting the demo back the way the scenario found it is therefore a
REQUIRED cleanup, not a way of hiding a defect.

The exception is scoped as tightly as the principle it bends:

  * it restores ONE named policy - the seeded ``m13-demo-active``;
  * it only ever moves the ACTIVE SLOT, so exactly one policy is active
    afterwards, which is the invariant the demo stack maintains;
  * it never deletes a policy, and it never touches the E2E-owned
    policies, which carry the evidence of the scenario;
  * it is still subject to every guard above - a non-demo database is
    refused just the same.

===========================================================================
USAGE
===========================================================================

    from scripts.e2e_fixtures_guard import GuardedContext, require_demo_database

    require_demo_database(GuardedContext.CORE, url, environ=os.environ)
"""

from __future__ import annotations

import os
from typing import Dict, FrozenSet, Mapping, Optional
from urllib.parse import urlsplit

#: The environment variable that carries the explicit opt-in.
#:
#: Its value is a space-separated list of database NAMES the helper is
#: allowed to write to.  A generic "true" authorises nothing: the
#: declaration has to name the target, so a declaration made for one
#: database cannot carry over to another.
E2E_WRITE_PERMISSION_VAR = "E2E_ALLOW_WRITE_TO"


class Context:
    """The three bounded contexts of the monolith."""

    CORE = "core"
    DETECTION = "detection"
    ML = "ml"

    ALL = (CORE, DETECTION, ML)


#: The database names each context owns, and the environment variable that
#: carries its URL.
#:
#: Each context owns exactly TWO names: the local demo stack's persistent
#: database and the CI disposable one.  They are disjoint from the
#: regression suite's ``*_test`` databases and from the canonical
#: production names, so a URL that resolves to one of them cannot be
#: mistaken for a demo database.
CONTEXT_DATABASES: Dict[str, FrozenSet[str]] = {
    Context.CORE: frozenset({"sentinel_core_demo", "sentinel_core_ci_demo"}),
    Context.DETECTION: frozenset({"sentinel_detection_demo", "sentinel_detection_ci_demo"}),
    Context.ML: frozenset({"sentinel_ml_demo", "sentinel_ml_ci_demo"}),
}

#: The environment variable that carries each context's URL.
CONTEXT_URL_VARS: Dict[str, str] = {
    Context.CORE: "CORE_DATABASE_URL",
    Context.DETECTION: "DETECTION_DATABASE_URL",
    Context.ML: "ML_DATABASE_URL",
}

#: The regression suite's disposable databases.  They are a different
#: vocabulary with a different owner, and they must never be reachable
#: from the E2E fixture helper.
PROTECTED_TEST_DATABASES: FrozenSet[str] = frozenset({
    "sentinel_core_test",
    "sentinel_detection_test",
    "sentinel_ml_test",
    "sentinel_legacy_test",
})

#: The canonical production database names.  These are what a real
#: deployment of this product uses, so a URL that resolves to one of them
#: is a production URL even if something else about it looks demo-ish.
PROTECTED_PRODUCTION_DATABASES: FrozenSet[str] = frozenset({
    "sentinel_core",
    "sentinel_detection",
    "sentinel_ml",
    "sentinel_auth",
    "sentinel",
    "postgres",
})

#: The hosts a demo database may live on.
#:
#: The local demo stack publishes PostgreSQL on the loopback interface,
#: and so does the CI job's service container.  A database on any other
#: host is a SHARED database, and a shared database is not the suite's to
#: mutate.
#:
#: The IPv6 loopback is listed in both its bare form (``::1``) and its
#: bracketed form (``[::1]``), because the two spellings of the same host
#: must not be a way around the check.
LOOPBACK_HOSTS: FrozenSet[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
})


class DemoDatabaseRefusal(Exception):
    """Raised when a URL is not a database the E2E suite may mutate.

    It is a distinct exception type rather than a bare ``SystemExit`` so
    that the refusal can be *tested* as a value: a test asserts that the
    guard refused, and it reads the reason out of the exception.
    """

    def __init__(self, reason: str, layer: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.layer = layer

    def __str__(self) -> str:  # pragma: no cover - the message is the point
        return f"[{self.layer}] {self.reason}"


def database_name_of(url: str) -> str:
    """Return the database name a connection URL points at.

    An empty string is returned when the URL does not name a database at
    all - which is itself a refusal, because a URL without a database
    cannot be proven disposable.
    """
    path = urlsplit(url).path
    return path.rsplit("/", 1)[-1] if path else ""


def host_of(url: str) -> str:
    """Return the host a connection URL points at.

    An empty string is returned when the URL names no host.
    """
    return urlsplit(url).hostname or ""


def _refuse(layer: str, reason: str) -> "DemoDatabaseRefusal":
    return DemoDatabaseRefusal(reason=reason, layer=layer)


def require_demo_database(
    context: str,
    url: str,
    environ: Optional[Mapping[str, str]] = None,
    allow_write_to: Optional[str] = None,
) -> str:
    """Refuse to continue unless ``url`` is a database this suite may mutate.

    :param context: the bounded context that owns the database - one of
        :data:`Context.CORE`, :data:`Context.DETECTION`,
        :data:`Context.ML`.
    :param url: the connection URL the helper is about to use.
    :param environ: the environment the declarations are read from.
        Defaults to ``os.environ``.
    :param allow_write_to: the database name the caller has declared it
        is allowed to write to.  Defaults to the value of the
        ``E2E_ALLOW_WRITE_TO`` environment variable.
    :return: the validated database name.
    :raises DemoDatabaseRefusal: when the URL is not an allowed demo
        database for this context.
    """
    env = os.environ if environ is None else environ

    if context not in CONTEXT_DATABASES:
        raise _refuse(
            "context",
            f"'{context}' is not a bounded context of the monolith. "
            f"The known contexts are: {', '.join(Context.ALL)}.",
        )

    if not url or not url.strip():
        raise _refuse(
            "url",
            f"{CONTEXT_URL_VARS[context]} is empty, so there is no target to "
            f"prove disposable.",
        )

    name = database_name_of(url)
    if not name:
        raise _refuse(
            "url",
            "the connection URL does not name a database, so it cannot be "
            "proven disposable.",
        )

    # --- Layer 2: the name allowlist ------------------------------------
    # The check is an EXACT match against the two names the context
    # owns.  A suffix check would be too weak: 'sentinel_core_demo_prod'
    # ends with neither '_demo' nor '_ci_demo' in the right place, and
    # 'sentinel_core_demo_backup' would pass a naive '_demo' check.
    allowed = CONTEXT_DATABASES[context]
    if name not in allowed:
        raise _refuse(
            "allowlist",
            f"the database '{name}' is not a demo database of the "
            f"'{context}' context. The '{context}' context may only ever "
            f"touch: {', '.join(sorted(allowed))}.",
        )

    # --- Layer 3: no overlap with the other vocabularies ----------------
    if name in PROTECTED_TEST_DATABASES:
        raise _refuse(
            "overlap",
            f"the database '{name}' belongs to the regression suite. The "
            f"E2E fixture helper must never reach a '*_test' database.",
        )

    if name in PROTECTED_PRODUCTION_DATABASES:
        raise _refuse(
            "overlap",
            f"the database '{name}' is a production database name. The E2E "
            f"fixture helper must never reach a production database.",
        )

    # --- Layer 4: the loopback host -------------------------------------
    host = host_of(url)
    if not host:
        raise _refuse(
            "host",
            "the connection URL names no host, so the target cannot be "
            "proven to be a local, throwaway server.",
        )

    if host not in LOOPBACK_HOSTS:
        raise _refuse(
            "host",
            f"the connection URL points at the host '{host}'. A demo "
            f"database must live on the loopback interface "
            f"({', '.join(sorted(LOOPBACK_HOSTS))}); a database on another "
            f"host is a SHARED database and is not the suite's to mutate.",
        )

    # --- Layer 5: the explicit opt-in -----------------------------------
    # The declaration must name the very database that is about to be
    # written to.  A generic acknowledgement authorises nothing, and a
    # declaration made for another target cannot carry over.
    declared = allow_write_to if allow_write_to is not None else env.get(
        E2E_WRITE_PERMISSION_VAR, ""
    )
    declared_names = {
        part for part in (declared or "").split() if part
    }

    if not declared_names:
        raise _refuse(
            "permission",
            f"the run has not declared that it may write to a demo "
            f"database. Set {E2E_WRITE_PERMISSION_VAR}={name} — naming the "
            f"exact database — before the E2E fixtures may write. The "
            f"helper refuses to mutate a database that nobody authorised.",
        )

    if name not in declared_names:
        raise _refuse(
            "permission",
            f"the run declared {E2E_WRITE_PERMISSION_VAR}="
            f"{' '.join(sorted(declared_names))!r}, but the helper is about "
            f"to write to '{name}'. The declaration must name the exact "
            f"target, so an authorisation for one database cannot carry "
            f"over to another.",
        )

    # --- Layer 1: the URL variable must belong to this context -----------
    # This is checked LAST, because it is the layer that catches the most
    # subtle mistake: a CORE_DATABASE_URL that was accidentally pointed at
    # the detection database.  The name check above already refused any
    # name the context does not own, so reaching this point means the
    # name IS one of the context's own - and this layer asserts that the
    # variable the URL came from is the context's own variable too.
    expected_var = CONTEXT_URL_VARS[context]
    configured = (env.get(expected_var, "") or "").strip()
    if not configured:
        raise _refuse(
            "context",
            f"{expected_var} is not set, so the '{context}' context has no "
            f"declared target.",
        )

    if configured.split("?", 1)[0] != url.split("?", 1)[0]:
        raise _refuse(
            "context",
            f"the URL the '{context}' context is about to use does not match "
            f"the {expected_var} it was taken from. The three bounded "
            f"contexts must each reach their OWN database.",
        )

    return name
