\connect ml_service

-- Local bootstrap schema for the ML-owned database. Production applies the
-- equivalent reviewed migration through the deployment migration runner.
CREATE TABLE feature_schemas (
  id uuid PRIMARY KEY,
  version integer NOT NULL UNIQUE CHECK (version > 0),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[a-f0-9]{64}$'),
  status text NOT NULL CHECK (status IN ('ACTIVE', 'DEPRECATED', 'RETIRED')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feature_definitions (
  feature_schema_id uuid NOT NULL REFERENCES feature_schemas(id),
  name text NOT NULL,
  position integer NOT NULL CHECK (position >= 0),
  data_type text NOT NULL CHECK (data_type IN ('INTEGER', 'NUMBER', 'BOOLEAN')),
  bounds jsonb NOT NULL,
  sensitivity text NOT NULL DEFAULT 'NONE' CHECK (sensitivity = 'NONE'),
  PRIMARY KEY (feature_schema_id, name),
  UNIQUE (feature_schema_id, position)
);

CREATE TABLE training_dataset_manifests (
  id uuid PRIMARY KEY,
  feature_schema_id uuid NOT NULL REFERENCES feature_schemas(id),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[a-f0-9]{64}$'),
  source_type text NOT NULL CHECK (source_type IN ('SYNTHETIC', 'CURATED')),
  generator_version text,
  sample_count bigint NOT NULL CHECK (sample_count > 0),
  contains_raw_security_data boolean NOT NULL DEFAULT false CHECK (contains_raw_security_data = false),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_artifacts (
  digest text PRIMARY KEY CHECK (digest ~ '^[a-f0-9]{64}$'),
  object_key text NOT NULL UNIQUE,
  media_type text NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
  id uuid PRIMARY KEY,
  version text NOT NULL UNIQUE,
  feature_schema_id uuid NOT NULL REFERENCES feature_schemas(id),
  training_dataset_manifest_id uuid NOT NULL REFERENCES training_dataset_manifests(id),
  artifact_digest text NOT NULL REFERENCES model_artifacts(digest),
  status text NOT NULL CHECK (status IN ('CANDIDATE', 'ACTIVE', 'RETIRED')),
  metrics jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_active_model_per_feature_schema
  ON model_versions (feature_schema_id)
  WHERE status = 'ACTIVE';

CREATE TABLE calibration_profiles (
  id uuid PRIMARY KEY,
  model_version_id uuid NOT NULL UNIQUE REFERENCES model_versions(id),
  method text NOT NULL CHECK (method = 'PERCENTILE_LINEAR_V1'),
  lower_bound numeric NOT NULL,
  upper_bound numeric NOT NULL,
  anomaly_threshold numeric NOT NULL CHECK (anomaly_threshold BETWEEN 0 AND 1),
  CHECK (upper_bound > lower_bound)
);

CREATE TABLE model_promotions (
  id uuid PRIMARY KEY,
  model_version_id uuid NOT NULL REFERENCES model_versions(id),
  decision text NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
  approved_by uuid,
  review_ref uuid,
  occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE inference_records (
  id uuid PRIMARY KEY,
  model_version_id uuid NOT NULL REFERENCES model_versions(id),
  input_digest text NOT NULL CHECK (input_digest ~ '^[a-f0-9]{64}$'),
  correlation_id uuid NOT NULL,
  status text NOT NULL CHECK (status IN ('SCORED', 'FAILED')),
  anomaly_score numeric CHECK (anomaly_score BETWEEN 0 AND 1),
  reason_codes jsonb NOT NULL,
  latency_ms integer NOT NULL CHECK (latency_ms >= 0),
  occurred_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (status = 'SCORED' AND anomaly_score IS NOT NULL)
    OR (status = 'FAILED' AND anomaly_score IS NULL)
  )
);

CREATE INDEX inference_records_correlation_idx ON inference_records (correlation_id, occurred_at DESC);
CREATE INDEX inference_records_model_time_idx ON inference_records (model_version_id, occurred_at DESC);
