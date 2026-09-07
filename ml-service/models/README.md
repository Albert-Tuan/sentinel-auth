# Local model registry

No trained artifact is committed to the repository. A model is executable only
when this directory contains a verified `active-model.json` and its matching
`.joblib` artifact. The manifest is immutable evidence: it records the feature
schema/order, artifact SHA-256, calibration, synthetic-data manifest, metrics
scope and promotion approval.

For a local demonstration only, build the deterministic synthetic model inside
the container or an environment with `requirements-ml.txt` installed:

```bash
python -m app.bootstrap_demo --output-dir models
```

This generates synthetic data; it is not a production fraud model and must not
be promoted outside a controlled model-review process.
