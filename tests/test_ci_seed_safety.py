"""Safety guards of the CI seed scripts.

The seed scripts of the frontend integration suite WRITE rows (the seed)
and DELETE rows (the cleanup). Both operations must never reach a real
deployment database, so the scripts refuse to run against a database
whose name does not carry the ``_test`` marker that marks a disposable
one.

The guard is tested here because it is the last line of defence before a
row is written or deleted. The tests are pure unit tests: they do not
connect to a database at all.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_script(name: str):
    """Import a script from ``scripts/`` by its file name."""
    path = SCRIPTS_DIR / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAlertSeedDatabaseGuard:
    """The guard of ``scripts/ci_seed_frontend_alerts.py``."""

    @pytest.fixture(scope="class")
    def module(self):
        return _load_script("ci_seed_frontend_alerts.py")

    def test_a_disposable_database_is_accepted(self, module):
        name = module.assert_disposable_database(
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_detection_test"
        )
        assert name == "sentinel_detection_test"

    def test_the_disposable_marker_is_the_one_the_bootstrap_uses(self, module):
        # The bootstrap script drops and recreates the disposable
        # databases; it uses the very same marker.
        assert module.DISPOSABLE_DB_MARKER == "_test"

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_detection",
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_core",
            "postgresql://sentinel:secret@127.0.0.1:5432/postgres",
            "postgresql://sentinel:secret@127.0.0.1:5432/sentinel_detection_prod",
        ],
    )
    def test_a_production_database_is_refused(self, module, url):
        with pytest.raises(SystemExit) as excinfo:
            module.assert_disposable_database(url)
        assert excinfo.value.code == 2

    def test_a_url_without_a_database_name_is_refused(self, module):
        with pytest.raises(SystemExit) as excinfo:
            module.assert_disposable_database(
                "postgresql://sentinel:secret@127.0.0.1:5432"
            )
        assert excinfo.value.code == 2

    def test_the_query_string_does_not_confuse_the_guard(self, module):
        # A URL may carry a query string; the database name is still the
        # path segment.
        name = module.assert_disposable_database(
            "postgresql://sentinel:secret@127.0.0.1:5432/"
            "sentinel_detection_test?sslmode=require"
        )
        assert name == "sentinel_detection_test"

    def test_the_cleanup_uses_the_same_marker_as_the_seed(self, module):
        # The seed and the cleanup identify their rows by ONE marker, so
        # the cleanup can never reach a row the seed did not create.
        assert module.FIXTURE_MARKER == "m12-stage4-fixture"

    def test_the_cleanup_only_touches_the_rows_of_the_fixtures(self, module):
        import inspect

        source = inspect.getsource(module.cleanup)
        # The query is scoped to the marker.
        assert "marker" in source
        # And nothing deletes a whole table.
        for forbidden in (".delete()", "delete(Alert)"):
            assert forbidden not in source
