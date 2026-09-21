#!/usr/bin/env python3
"""
Sentinel Auth - ML Model Training Script
=========================================

Trains the initial Isolation Forest model for anomaly detection in login events.

Output:
    app/ml_models/isolation-forest-v1.0.joblib

Usage:
    # Generate synthetic data and train
    python scripts/train_model.py

    # Use real data from CSV
    python scripts/train_model.py --data path/to/training_data.csv

    # Custom hyperparameters
    python scripts/train_model.py --contamination 0.15 --n-estimators 200

The 6 input features (must match contract with detection-engine):
    1. hour_of_day: int 0-23
    2. fail_count_24h: int >=0
    3. ip_change_rate_7d: float 0-1
    4. new_device: bool (0/1)
    5. average_login_interval_seconds: int >=0
    6. deviation_score: float 0-1
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

FEATURE_NAMES = [
    "hour_of_day",
    "fail_count_24h",
    "ip_change_rate_7d",
    "new_device",
    "average_login_interval_seconds",
    "deviation_score",
]

MODEL_VERSION = "v1.0-isolation-forest"
MODEL_NAME = "Isolation Forest v1.0"
MODEL_DIR = Path(__file__).resolve().parent.parent / "app" / "ml_models"
MODEL_PATH = MODEL_DIR / f"{MODEL_VERSION}.joblib"
METADATA_PATH = MODEL_DIR / f"{MODEL_VERSION}.metadata.json"

DEFAULT_CONFIG = {
    "threshold": 0.5,
    "contamination": 0.1,
    "n_estimators": 100,
    "max_samples": "auto",
    "random_state": 42,
}


# -----------------------------------------------------------------------------
# Synthetic Data Generation (for initial bootstrap)
# -----------------------------------------------------------------------------

def generate_synthetic_training_data(n_samples: int = 10000, random_state: int = 42):
    """
    Generate synthetic login behavior data for initial training.

    Distribution strategy:
    - 90% normal behavior (label=0)
    - 10% anomalous behavior (label=1) - reflects real-world base rate

    Anomalies have:
    - Unusual hours (night time)
    - High fail counts
    - High IP change rates
    - New devices
    - Large gaps between logins
    - High deviation scores
    """
    rng = np.random.default_rng(random_state)

    # Normal samples
    n_normal = int(n_samples * 0.9)
    n_anomaly = n_samples - n_normal

    # Normal user behavior:
    # - Hours: bell curve around 9-17 (work hours)
    # - Fail count: low (0-2)
    # - IP change rate: low (0-0.2)
    # - New device: rare
    # - Login interval: stable (regular hours)
    # - Deviation score: low (0-0.3)
    normal_data = np.column_stack([
        rng.normal(loc=13, scale=4, size=n_normal).clip(0, 23).astype(int),    # hour_of_day
        rng.poisson(lam=0.5, size=n_normal).clip(0, 10),                        # fail_count_24h
        rng.beta(a=2, b=10, size=n_normal),                                      # ip_change_rate_7d
        rng.binomial(1, 0.05, size=n_normal),                                    # new_device (rare)
        rng.normal(loc=28800, scale=7200, size=n_normal).clip(0, 86400),        # avg_login_interval
        rng.beta(a=2, b=8, size=n_normal),                                       # deviation_score
    ])

    # Anomalous behavior:
    # - Hours: spread, often outside work hours
    # - Fail count: high (3-10)
    # - IP change rate: high (0.5-1.0)
    # - New device: common
    # - Login interval: irregular
    # - Deviation score: high (0.5-1.0)
    anomaly_data = np.column_stack([
        rng.uniform(0, 23, size=n_anomaly).astype(int),                          # hour_of_day (any)
        rng.poisson(lam=5, size=n_anomaly).clip(3, 15),                          # fail_count_24h
        rng.beta(a=5, b=2, size=n_anomaly),                                      # ip_change_rate_7d (high)
        rng.binomial(1, 0.7, size=n_anomaly),                                    # new_device (common)
        rng.uniform(0, 200000, size=n_anomaly),                                  # avg_login_interval (irregular)
        rng.beta(a=5, b=2, size=n_anomaly),                                      # deviation_score (high)
    ])

    X = np.vstack([normal_data, anomaly_data])
    y = np.concatenate([np.zeros(n_normal), np.ones(n_anomaly)])

    # Shuffle
    shuffle_idx = rng.permutation(len(X))
    X = X[shuffle_idx]
    y = y[shuffle_idx]

    return pd.DataFrame(X, columns=FEATURE_NAMES), pd.Series(y, name="is_anomaly")


# -----------------------------------------------------------------------------
# Training Pipeline
# -----------------------------------------------------------------------------

def train_model(X_train: pd.DataFrame, config: dict) -> IsolationForest:
    """Train Isolation Forest with given config."""
    print(f"[INFO] Training Isolation Forest with config: {config}")

    model = IsolationForest(
        n_estimators=config["n_estimators"],
        contamination=config["contamination"],
        max_samples=config["max_samples"],
        random_state=config["random_state"],
        n_jobs=-1,
        verbose=0,
    )

    model.fit(X_train)
    print(f"[INFO] Training complete. Estimators: {len(model.estimators_)}")
    return model


def evaluate_model(model: IsolationForest, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """Evaluate model and return metrics dict."""
    # Predict: -1 = anomaly, 1 = normal
    y_pred_raw = model.predict(X_test)
    # Convert to 0/1 (1 = anomaly)
    y_pred = (y_pred_raw == -1).astype(int)

    # decision_function: lower = more anomalous (negative for anomalies)
    raw_scores = model.decision_function(X_test)
    # Normalize to 0-1 (higher = more anomalous)
    normalized_scores = 1.0 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min() + 1e-10)

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_test, y_pred, zero_division=0)),
        "accuracy": float((y_pred == y_test).mean()),
        "support_total": int(len(y_test)),
        "support_anomaly": int(y_test.sum()),
    }

    # AUC-ROC (only valid if both classes present)
    if y_test.nunique() == 2:
        metrics["auc_roc"] = float(roc_auc_score(y_test, normalized_scores))

    print("\n[EVAL] Classification Report:")
    print(classification_report(y_test, y_pred, target_names=["normal", "anomaly"], zero_division=0))
    print(f"[EVAL] Metrics: {json.dumps(metrics, indent=2)}")

    return metrics


def save_model(model: IsolationForest, config: dict, metrics: dict) -> None:
    """Save model and metadata."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Save model
    joblib.dump(model, MODEL_PATH)
    print(f"[INFO] Model saved to {MODEL_PATH}")

    # Save metadata (matches schema: model_versions.config JSONB)
    metadata = {
        "name": MODEL_NAME,
        "version": MODEL_VERSION,
        "algorithm": "IsolationForest",
        "description": "Baseline Isolation Forest model for anomaly detection in login events",
        "model_path": str(MODEL_PATH),
        "config": {
            **config,
            "training_date": datetime.utcnow().isoformat() + "Z",
            "training_features": FEATURE_NAMES,
            "metrics": metrics,
        },
        "status": "active",
        "is_production": True,
        "trained_at": datetime.utcnow().isoformat() + "Z",
    }

    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[INFO] Metadata saved to {METADATA_PATH}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train Sentinel Auth ML model")
    parser.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to CSV file with training data (must have columns: hour_of_day, fail_count_24h, ip_change_rate_7d, new_device, average_login_interval_seconds, deviation_score, is_anomaly)",
    )
    parser.add_argument("--n-samples", type=int, default=10000, help="Number of synthetic samples if no data provided")
    parser.add_argument("--contamination", type=float, default=0.1, help="Expected proportion of anomalies")
    parser.add_argument("--n-estimators", type=int, default=100, help="Number of trees in the forest")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split ratio")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    print(f"[INFO] Starting training pipeline for {MODEL_VERSION}")
    print(f"[INFO] Features: {FEATURE_NAMES}")

    # Load or generate data
    if args.data:
        print(f"[INFO] Loading training data from {args.data}")
        df = pd.read_csv(args.data)
        if not all(col in df.columns for col in FEATURE_NAMES + ["is_anomaly"]):
            print(f"[ERROR] CSV must have columns: {FEATURE_NAMES + ['is_anomaly']}")
            sys.exit(1)
        X = df[FEATURE_NAMES]
        y = df["is_anomaly"]
    else:
        print(f"[INFO] No data provided, generating {args.n_samples} synthetic samples")
        X, y = generate_synthetic_training_data(args.n_samples, args.random_state)

    print(f"[INFO] Dataset shape: {X.shape}, anomalies: {y.sum()} ({100*y.mean():.1f}%)")

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=args.test_size, random_state=args.random_state, stratify=y
    )
    print(f"[INFO] Train: {len(X_train)}, Test: {len(X_test)}")

    # Train
    config = {
        **DEFAULT_CONFIG,
        "contamination": args.contamination,
        "n_estimators": args.n_estimators,
        "random_state": args.random_state,
    }
    model = train_model(X_train, config)

    # Evaluate
    metrics = evaluate_model(model, X_test, y_test)

    # Save
    save_model(model, config, metrics)

    print("\n[SUCCESS] Training pipeline complete!")
    print(f"  Model:       {MODEL_PATH}")
    print(f"  Metadata:    {METADATA_PATH}")
    print(f"  F1 Score:    {metrics['f1_score']:.4f}")
    print(f"  AUC-ROC:     {metrics.get('auc_roc', 'N/A')}")


if __name__ == "__main__":
    main()
