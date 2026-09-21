"""Fake settings used across the test suite.

Lives under ``tests/`` so it cannot import the deployment-only
``Settings.from_env()`` module that reads real env vars.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FakeSettings:
    """Drop-in replacement for ``app.contracts.settings.Settings`` in tests."""

    database_url: str
    redis_url: str
    model_dir: Path
    internal_dev_token: str
    environment: str
    ml_timeout_ms: int

    @classmethod
    def default(cls, model_dir: Path) -> "FakeSettings":
        return cls(
            database_url="postgresql+psycopg://sentinel:change-me-for-local-only@localhost:5432/sentinel",
            redis_url="redis://localhost:6379/0",
            model_dir=model_dir,
            internal_dev_token="test-workload-token",
            environment="test",
            ml_timeout_ms=500,
        )
