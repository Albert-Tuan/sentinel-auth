"""Create an explicitly opt-in synthetic Isolation Forest artifact for local demos."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.model_registry import sha256_file
from app.schemas import FEATURE_NAMES, FEATURE_SCHEMA_VERSION


def build_baseline(*, seed: int, samples: int) -> list[list[float]]:
    """Synthetic normal login population; it is never a claim of fraud accuracy."""

    rng = random.Random(seed)
    result: list[list[float]] = []
    for _ in range(samples):
        result.append(
            [
                min(23.0, max(0.0, rng.gauss(13.0, 3.5))),
                max(0.0, rng.expovariate(1 / 0.7)),
                min(1.0, max(0.0, rng.betavariate(1.5, 9))),
                1.0 if rng.random() < 0.08 else 0.0,
                max(30.0, rng.lognormvariate(math.log(36_000), 0.7)),
                min(1.0, max(0.0, rng.betavariate(2, 12))),
            ]
        )
    return result


def bootstrap(*, output_dir: Path, seed: int, samples: int, version: str) -> Path:
    """Fit, calibrate, digest and promote a synthetic model for local use only."""

    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError as error:
        raise RuntimeError("Install requirements-ml.txt before bootstrapping a demo model") from error

    output_dir.mkdir(parents=True, exist_ok=True)
    population = build_baseline(seed=seed, samples=samples)
    estimator = IsolationForest(
        n_estimators=200,
        contamination=0.02,
        random_state=seed,
        n_jobs=1,
    ).fit(population)
    raw_scores = -estimator.score_samples(population)
    artifact_name = f"{version}.joblib"
    artifact_path = output_dir / artifact_name
    joblib.dump(estimator, artifact_path)

    dataset_manifest = {
        "id": str(uuid4()),
        "kind": "SYNTHETIC_BASELINE_V1",
        "generator_version": "sentinel-auth-synthetic-v1",
        "seed": seed,
        "sample_count": samples,
        "contains_raw_security_data": False,
    }
    dataset_manifest_json = json.dumps(dataset_manifest, sort_keys=True, separators=(",", ":"))
    manifest = {
        "id": str(uuid4()),
        "version": version,
        "status": "ACTIVE",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "artifact": {"file": artifact_name, "sha256": sha256_file(artifact_path)},
        "training_dataset": {
            **dataset_manifest,
            "digest": hashlib.sha256(dataset_manifest_json.encode("utf-8")).hexdigest(),
        },
        "metrics": {
            "data_scope": "SYNTHETIC_ONLY",
            "baseline_sample_count": samples,
            "note": "Synthetic metrics must not be represented as production detection quality.",
        },
        "calibration": {
            "method": "PERCENTILE_LINEAR_V1",
            "lower_bound": float(np.quantile(raw_scores, 0.05)),
            "upper_bound": float(np.quantile(raw_scores, 0.99)),
            "anomaly_threshold": 0.80,
        },
        "promotion": {
            "decision": "APPROVED",
            "approved_by": "LOCAL_DEMO_BOOTSTRAP",
            "approved_at": datetime.now(UTC).isoformat(),
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = output_dir / "active-model.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("models"))
    parser.add_argument("--seed", type=int, default=20260907)
    parser.add_argument("--samples", type=int, default=1_000)
    parser.add_argument("--version", default="demo-iforest-v1")
    arguments = parser.parse_args()
    manifest = bootstrap(
        output_dir=arguments.output_dir,
        seed=arguments.seed,
        samples=arguments.samples,
        version=arguments.version,
    )
    print(f"Created local-only model manifest: {manifest}")


if __name__ == "__main__":
    main()
