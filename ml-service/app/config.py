"""Configuration kept deliberately small and explicit for the private workload."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    ``internal_dev_token`` is a Compose-only compatibility mechanism.  A
    production deployment must put this service behind workload mTLS/JWT
    validation and set a non-default secret through its secret manager.
    """

    model_dir: Path
    internal_dev_token: str
    environment: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model_dir=Path(os.getenv("ML_MODEL_DIR", "models")),
            internal_dev_token=os.getenv("INTERNAL_DEV_TOKEN", "local-dev-token-only"),
            environment=os.getenv("APP_ENV", "development"),
        )
