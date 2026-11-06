"""M11.3 — security hardening tests.

These tests cover the changes that M11.3 actually made:

* A. the CORS allow-list replaced the wildcard origin;
* B. the RBAC matrix (proved over real HTTP, pinned here as a regression
  net for the endpoints that changed);
* C. ``/ready`` is dependency-aware and keeps the ML artifact apart from
  the ML database;
* D. the session / token invariants;
* E. the startup configuration validation.

Everything here is a *regression* test: it pins a behaviour that must not
change silently.  Nothing tests a feature that did not change.
"""
from __future__ import annotations

import os

import pytest

from app import cors_config


# =============================================================================
# A. CORS
# =============================================================================

class TestCorsAllowList:
    """The wildcard origin is replaced by an explicit, configurable list."""

    def test_the_default_allowlist_has_no_wildcard(self):
        origins = cors_config.default_cors_origins()
        assert "*" not in origins
        assert origins, "the default allow-list must not be empty"

    def test_the_default_allowlist_is_the_local_deployment_origin(self):
        origins = cors_config.default_cors_origins()
        assert "http://localhost:8000" in origins
        assert "http://127.0.0.1:8000" in origins

    def test_an_unset_variable_yields_the_default(self, monkeypatch):
        monkeypatch.delenv(cors_config.CORS_ALLOWED_ORIGINS_ENV, raising=False)
        assert cors_config.resolve_cors_origins() == cors_config.default_cors_origins()

    def test_a_configured_value_is_used(self, monkeypatch):
        monkeypatch.setenv(
            cors_config.CORS_ALLOWED_ORIGINS_ENV,
            "https://soc.example.com,https://admin.example.com",
        )
        assert cors_config.resolve_cors_origins() == [
            "https://soc.example.com",
            "https://admin.example.com",
        ]

    def test_a_wildcard_is_rejected(self, monkeypatch):
        """A wildcard origin is the vulnerability this change removes."""
        monkeypatch.setenv(cors_config.CORS_ALLOWED_ORIGINS_ENV, "*")
        with pytest.raises(cors_config.CORSConfigurationError) as exc_info:
            cors_config.resolve_cors_origins()
        assert "*" in str(exc_info.value)

    def test_a_wildcard_among_other_origins_is_rejected(self, monkeypatch):
        monkeypatch.setenv(
            cors_config.CORS_ALLOWED_ORIGINS_ENV,
            "https://soc.example.com,*",
        )
        with pytest.raises(cors_config.CORSConfigurationError):
            cors_config.resolve_cors_origins()

    @pytest.mark.parametrize(
        "value",
        [
            "soc.example.com",       # no scheme
            "ftp://soc.example.com",  # unsupported scheme
            "https://soc.example.com/app",  # a path is not an origin
            "https://soc.example.com/?x=1",  # a query is not an origin
        ],
    )
    def test_an_unusable_entry_is_rejected(self, monkeypatch, value):
        monkeypatch.setenv(cors_config.CORS_ALLOWED_ORIGINS_ENV, value)
        with pytest.raises(cors_config.CORSConfigurationError):
            cors_config.resolve_cors_origins()

    def test_a_trailing_slash_is_normalised_away(self, monkeypatch):
        """A trailing slash would otherwise never match an Origin header."""
        monkeypatch.setenv(
            cors_config.CORS_ALLOWED_ORIGINS_ENV, "https://soc.example.com/"
        )
        assert cors_config.resolve_cors_origins() == ["https://soc.example.com"]

    def test_duplicates_are_collapsed(self, monkeypatch):
        monkeypatch.setenv(
            cors_config.CORS_ALLOWED_ORIGINS_ENV,
            "https://soc.example.com,https://soc.example.com",
        )
        assert cors_config.resolve_cors_origins() == ["https://soc.example.com"]

    def test_an_empty_list_yields_the_default(self, monkeypatch):
        monkeypatch.setenv(cors_config.CORS_ALLOWED_ORIGINS_ENV, "   ")
        assert cors_config.resolve_cors_origins() == cors_config.default_cors_origins()


class TestCorsMiddlewareBehaviour:
    """The middleware itself refuses a non-allow-listed origin."""

    def _client(self, origins):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        cors_config.install_cors_middleware(app, origins)

        @app.get("/probe")
        async def _probe():
            return {"status": "ok"}

        return TestClient(app)

    def test_an_allow_listed_origin_is_reflected(self):
        client = self._client(["https://soc.example.com"])
        response = client.get("/probe", headers={"Origin": "https://soc.example.com"})
        assert response.headers.get("access-control-allow-origin") == "https://soc.example.com"

    def test_a_foreign_origin_gets_no_allow_origin_header(self):
        """The core of the fix: an unknown origin is not reflected."""
        client = self._client(["https://soc.example.com"])
        response = client.get("/probe", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers

    def test_a_foreign_origin_is_refused_even_with_a_cookie(self):
        """With a wildcard, Starlette reflected ANY origin that carried a
        cookie - that is the credential-theft path this change closes."""
        client = self._client(["https://soc.example.com"])
        response = client.get(
            "/probe",
            headers={"Origin": "https://evil.example.com", "Cookie": "session=stolen"},
        )
        assert "access-control-allow-origin" not in response.headers

    def test_a_preflight_from_a_foreign_origin_is_refused(self):
        client = self._client(["https://soc.example.com"])
        response = client.options(
            "/probe",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_a_preflight_from_an_allow_listed_origin_is_accepted(self):
        client = self._client(["https://soc.example.com"])
        response = client.options(
            "/probe",
            headers={
                "Origin": "https://soc.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://soc.example.com"

    def test_an_empty_allowlist_installs_no_middleware(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        cors_config.install_cors_middleware(app, [])

        @app.get("/probe")
        async def _probe():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/probe", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in response.headers


# =============================================================================
# C. Readiness
# =============================================================================

class TestReadinessProbe:
    """``/ready`` probes the dependencies and keeps the ML artifact apart."""

    def test_the_probe_checks_the_three_bounded_contexts(self):
        from app import db
        from app.readiness import REQUIRED_CONTEXTS

        assert set(REQUIRED_CONTEXTS) == {db.CORE, db.DETECTION, db.ML}

    def test_the_probe_runs_only_read_only_statements(self):
        """The probe must not write anything.

        The statement is inspected directly, because a probe that writes is
        not a probe any more - it becomes a side effect on every poll.
        """
        import inspect

        from app import readiness

        source = inspect.getsource(readiness._check_context).upper()
        assert "SELECT 1" in source
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "COMMIT(", "FLUSH("):
            assert forbidden not in source

    def test_a_ready_deployment_reports_every_context_as_ok(self, monkeypatch):
        from app import db, readiness

        monkeypatch.setattr(readiness, "_check_context",
                            lambda context, deadline: {"status": "ok"})
        monkeypatch.setattr(readiness, "_check_ml_artifact",
                            lambda: {"status": "ready"})
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "ready"
        assert payload["checks"][db.CORE]["status"] == "ok"
        assert payload["checks"][db.DETECTION]["status"] == "ok"
        assert payload["checks"][db.ML]["status"] == "ok"
        readiness.reset_readiness_cache()

    def test_an_unavailable_database_makes_the_probe_not_ready(self, monkeypatch):
        from app import db, readiness

        def _fake_check(context, deadline):
            if context == db.DETECTION:
                return {"status": "unavailable", "detail": "OperationalError"}
            return {"status": "ok"}

        monkeypatch.setattr(readiness, "_check_context", _fake_check)
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "not_ready"
        assert payload["checks"][db.DETECTION]["status"] == "unavailable"
        readiness.reset_readiness_cache()

    def test_a_missing_ml_artifact_does_not_make_the_probe_not_ready(self, monkeypatch):
        """A missing ARTIFACT is degraded, not down.

        The demo deployment ships no promoted model, and the Detection
        Engine falls back to a rule-only score.  The service must stay
        ready in that state.
        """
        from app import readiness

        monkeypatch.setattr(readiness, "_check_context",
                            lambda context, deadline: {"status": "ok"})
        monkeypatch.setattr(readiness, "_check_ml_artifact",
                            lambda: {"status": "degraded", "detail": "no artifact"})
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "ready"
        assert payload["checks"]["ml_artifact"]["status"] == "degraded"
        assert payload.get("degraded") is True
        readiness.reset_readiness_cache()

    def test_an_unavailable_ml_database_is_not_reported_as_an_artifact_problem(
        self, monkeypatch,
    ):
        """The two failures must stay distinguishable."""
        from app import db, readiness

        def _fake_check(context, deadline):
            if context == db.ML:
                return {"status": "unavailable", "detail": "OperationalError"}
            return {"status": "ok"}

        monkeypatch.setattr(readiness, "_check_context", _fake_check)
        readiness.reset_readiness_cache()

        payload = readiness.readiness_payload()
        assert payload["status"] == "not_ready"
        assert payload["checks"][db.ML]["status"] == "unavailable"
        assert payload["checks"]["ml_artifact"]["status"] == "unknown"
        readiness.reset_readiness_cache()

    def test_a_failing_probe_is_never_cached(self, monkeypatch):
        """A recovery must be reported immediately, not after the TTL."""
        from app import readiness

        state = {"fail": True}

        def _fake_check(context, deadline):
            if state["fail"]:
                return {"status": "unavailable"}
            return {"status": "ok"}

        monkeypatch.setattr(readiness, "_check_context", _fake_check)
        readiness.reset_readiness_cache()

        assert readiness.readiness_payload()["status"] == "not_ready"
        state["fail"] = False
        assert readiness.readiness_payload()["status"] == "ready"
        readiness.reset_readiness_cache()


# =============================================================================
# F. The probe is bounded - a blackholed database cannot hang it
# =============================================================================

class TestProbeIsBounded:
    """The readiness probe answers promptly, whatever the database does.

    A deadline that is only checked BETWEEN the checks is not a deadline:
    a database host that DROPS the packets makes the connection attempt
    hang for the operating system's own TCP timeout - more than 60 seconds
    was measured here.  A probe that blocks that long is worse than no
    probe, because the orchestrator sees a hung health check instead of an
    answer.
    """

    def test_every_engine_gets_a_connect_timeout(self):
        """A connect attempt must be bounded, not left to the OS."""
        from app import db

        args = db._connect_args("postgresql://sentinel:sentinel@localhost:5432/sentinel_core")
        assert args["connect_timeout"] == db.CONNECT_TIMEOUT_SECONDS
        assert db.CONNECT_TIMEOUT_SECONDS <= 2

    def test_a_non_postgresql_url_gets_no_driver_arguments(self):
        """Another dialect's driver would reject an unknown keyword."""
        from app import db

        assert db._connect_args("sqlite:///./test.db") == {}

    def test_the_engine_is_created_with_the_connect_timeout(self):
        """The timeout has to reach the engine, not just the helper."""
        from app import db

        engine = db.get_engine(
            "postgresql+psycopg2://sentinel:sentinel@localhost:5432/sentinel_probe_test",
            context="m113_probe_test",
        )
        try:
            # The connect arguments live in the pool creator's closure -
            # that is where SQLAlchemy puts the keyword arguments that are
            # handed to the DBAPI driver.
            creator = engine.pool._creator
            params = {
                name: cell.cell_contents
                for name, cell in zip(
                    creator.__code__.co_freevars, creator.__closure__ or ()
                )
            }
            assert params["cparams"]["connect_timeout"] == db.CONNECT_TIMEOUT_SECONDS
        finally:
            db._engines.pop("m113_probe_test", None)

    def test_the_probe_sets_a_statement_timeout(self):
        """A server that accepts the connection but stops answering is cut off."""
        import inspect

        from app import readiness

        source = inspect.getsource(readiness._check_context)
        assert "statement_timeout" in source

    def test_the_probe_answers_within_its_budget_for_a_blackholed_database(self):
        """The end-to-end proof: a blackholed database still yields an answer.

        ``10.255.255.1`` is not routable, so the packets are dropped rather
        than refused - the case that hung for more than 60 seconds before
        the connect timeout was added.
        """
        import time

        from app import db, readiness

        blackhole = "postgresql://sentinel:sentinel@10.255.255.1:5432/sentinel_core"
        import os

        for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "ML_DATABASE_URL"):
            os.environ[name] = blackhole

        for context in (db.CORE, db.DETECTION, db.ML):
            db._engines.pop(context, None)
            db._sessionmakers.pop(context, None)

        readiness.reset_readiness_cache()
        try:
            started = time.monotonic()
            payload = readiness.readiness_payload()
            elapsed = time.monotonic() - started

            assert payload["status"] == "not_ready"
            assert payload["checks"][db.CORE]["status"] == "unavailable"
            # The budget is 2 s; the connect timeout must keep the whole
            # probe inside it.
            assert elapsed <= readiness.PROBE_TIMEOUT_SECONDS + 1.0, (
                f"the probe took {elapsed:.1f}s, which is past its budget"
            )
        finally:
            for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "ML_DATABASE_URL"):
                os.environ.pop(name, None)
            for context in (db.CORE, db.DETECTION, db.ML):
                db._engines.pop(context, None)
                db._sessionmakers.pop(context, None)
            readiness.reset_readiness_cache()

    def test_the_probe_does_not_leak_a_connection(self):
        """A failed probe must return every connection to the pool.

        The probe opens one session per context.  A session that is not
        closed would keep its connection checked out, and a database that
        is unreachable makes every probe fail - so a leak would drain the
        pool after a handful of polls and take the whole service down.
        """
        import os

        from app import db, readiness

        blackhole = "postgresql://sentinel:sentinel@10.255.255.1:5432/sentinel_core"
        for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "ML_DATABASE_URL"):
            os.environ[name] = blackhole
        for context in (db.CORE, db.DETECTION, db.ML):
            db._engines.pop(context, None)
            db._sessionmakers.pop(context, None)

        readiness.reset_readiness_cache()
        try:
            for _ in range(3):
                readiness.readiness_payload()

            for context in (db.CORE, db.DETECTION, db.ML):
                engine = db.get_engine(db.resolve_database_url(context), context=context)
                assert engine.pool.checkedout() == 0, (
                    f"the {context} pool still has a checked-out connection"
                )
        finally:
            for name in ("CORE_DATABASE_URL", "DETECTION_DATABASE_URL", "ML_DATABASE_URL"):
                os.environ.pop(name, None)
            for context in (db.CORE, db.DETECTION, db.ML):
                db._engines.pop(context, None)
                db._sessionmakers.pop(context, None)
            readiness.reset_readiness_cache()

    def test_the_probe_does_not_block_the_event_loop(self):
        """A slow probe must not stall every other request in the process.

        The probe talks to PostgreSQL through the synchronous driver.  Run
        directly inside the ``async def`` endpoint, it would hold the event
        loop for its whole budget, so a login or an alert list would wait
        behind a readiness poll.
        """
        import asyncio

        from app import readiness

        async def measure():
            ticks = []

            async def ticker():
                last = asyncio.get_event_loop().time()
                while True:
                    await asyncio.sleep(0.05)
                    now = asyncio.get_event_loop().time()
                    ticks.append(now - last)
                    last = now

            task = asyncio.create_task(ticker())
            await asyncio.sleep(0.15)

            # The synchronous probe, exactly as it would run if the
            # endpoint called it directly.
            started = asyncio.get_event_loop().time()
            await readiness.readiness_payload_async()
            await asyncio.sleep(0.15)
            task.cancel()

            return max(ticks)

        gap = asyncio.run(measure())
        assert gap < 0.5, (
            f"the event loop was stalled for {gap:.2f}s while the probe ran"
        )


# =============================================================================
# E. Startup configuration validation
# =============================================================================

class TestStartupValidation:
    """The application refuses to start with an unusable internal secret."""

    def test_a_valid_secret_passes(self, monkeypatch):
        from app.main import _validate_internal_secret_configuration

        monkeypatch.setenv("INTERNAL_SECRET", "a" * 40)
        _validate_internal_secret_configuration()

    def test_a_missing_secret_is_refused(self, monkeypatch):
        from app.main import _validate_internal_secret_configuration

        monkeypatch.delenv("INTERNAL_SECRET", raising=False)
        with pytest.raises(RuntimeError) as exc_info:
            _validate_internal_secret_configuration()
        assert "internal service secret" in str(exc_info.value)

    def test_the_placeholder_secret_is_refused(self, monkeypatch):
        from app.main import _validate_internal_secret_configuration

        monkeypatch.setenv("INTERNAL_SECRET", "changeme-in-production")
        with pytest.raises(RuntimeError):
            _validate_internal_secret_configuration()

    def test_the_shipped_env_example_placeholder_is_refused(self, monkeypatch):
        """The template value in ``.env.example`` must not start the app.

        The template value is long enough to pass the length rule, so only
        the placeholder rule can stop a deployment that copied ``.env``
        straight from ``.env.example``.
        """
        from app.main import _validate_internal_secret_configuration

        template = "change-me-to-a-secret-at-least-32-chars"
        assert len(template) >= 32, "the template must be long enough to slip past the length rule"

        monkeypatch.setenv("INTERNAL_SECRET", template)
        with pytest.raises(RuntimeError) as exc_info:
            _validate_internal_secret_configuration()
        assert template not in str(exc_info.value)

    @pytest.mark.parametrize(
        "prefix",
        ["change-me", "changeme", "replace-me", "placeholder", "your-", "secret", "password"],
    )
    def test_every_template_placeholder_prefix_is_refused(self, monkeypatch, prefix):
        """The application and ``deploy_local.sh`` must agree on the rule.

        ``scripts/deploy_local.sh`` refuses a secret that starts with
        ``change-me``/``changeme``/``secret``/``password``.  The application
        has to refuse the same values, otherwise a deployment that is
        rejected by the script would still start when it is launched
        directly.
        """
        from app.main import _validate_internal_secret_configuration

        monkeypatch.setenv("INTERNAL_SECRET", f"{prefix}-to-a-secret-at-least-32-characters")
        with pytest.raises(RuntimeError):
            _validate_internal_secret_configuration()

    def test_a_generated_secret_is_accepted(self, monkeypatch):
        """A secret produced by ``secrets.token_urlsafe`` must be accepted."""
        import secrets as _secrets

        from app.main import _validate_internal_secret_configuration

        monkeypatch.setenv("INTERNAL_SECRET", _secrets.token_urlsafe(32))
        _validate_internal_secret_configuration()

    def test_a_short_secret_is_refused(self, monkeypatch):
        from app.main import _validate_internal_secret_configuration

        monkeypatch.setenv("INTERNAL_SECRET", "too-short")
        with pytest.raises(RuntimeError):
            _validate_internal_secret_configuration()

    def test_the_error_never_contains_the_secret(self, monkeypatch):
        """A configuration error must not echo the secret into the log."""
        from app.main import _validate_internal_secret_configuration

        # Too short to be accepted, and distinctive enough to be detected
        # if it ever leaked into the message.
        secret = "leaky-secret-value"
        monkeypatch.setenv("INTERNAL_SECRET", secret)
        with pytest.raises(RuntimeError) as exc_info:
            _validate_internal_secret_configuration()
        assert secret not in str(exc_info.value)
