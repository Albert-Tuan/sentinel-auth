"""Guard rails that keep the ORM, the SQL schemas and the canonical spec aligned.

These tests fail the moment somebody renames a column in only one of the three
places. See docs/DECISIONS-DETECTION-v3.3.md section 8 for the full checklist.
"""
import re
from pathlib import Path

import pytest
from sqlalchemy.ext.compiler import compiles

from app.db import Base
from app import models as M

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "infra/postgres"
SPEC = ROOT / "docs/DECISIONS-DETECTION-v3.3.md"


# =============================================================================
# Helpers
# =============================================================================

def _strip_sql_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"^\s*--.*$", "", text, flags=re.M)


def _sql_tables() -> dict:
    tables: dict[str, set[str]] = {}
    for path in sorted(SQL_DIR.glob("schema-*.sql")):
        text = _strip_sql_comments(path.read_text())
        for match in re.finditer(
            r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", text, re.S
        ):
            name, body = match.group(1), match.group(2)
            cols: set[str] = set()
            depth, buf = 0, ""
            for line in body.split("\n"):
                if not line.strip():
                    continue
                buf += " " + line.strip()
                depth += line.count("(") - line.count(")")
                if depth == 0:
                    head = buf.strip().split(" ", 1)[0].upper()
                    if head not in {"PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE", "CHECK", "EXCLUDE"}:
                        cols.add(buf.strip().split(" ", 1)[0])
                    buf = ""
            tables.setdefault(name, set()).update(cols)
    return tables


def _orm_tables() -> dict:
    out: dict[str, set[str]] = {}
    for obj in vars(M).values():
        table = getattr(obj, "__tablename__", None)
        if table and hasattr(obj, "__table__"):
            out[table] = {c.name for c in obj.__table__.columns}
    return out


SQL_TABLES = _sql_tables()
ORM_TABLES = _orm_tables()


# =============================================================================
# ORM <-> SQL
# =============================================================================

@pytest.mark.parametrize("table", sorted(ORM_TABLES))
def test_orm_table_exists_in_sql(table):
    assert table in SQL_TABLES, f"ORM model {table} has no CREATE TABLE in infra/postgres/"


@pytest.mark.parametrize("table", sorted(SQL_TABLES))
def test_sql_table_has_orm_model(table):
    assert table in ORM_TABLES, f"Table {table} exists in SQL but has no ORM model"


@pytest.mark.parametrize("table", sorted(set(ORM_TABLES) & set(SQL_TABLES)))
def test_columns_match(table):
    only_sql = sorted(SQL_TABLES[table] - ORM_TABLES[table])
    only_orm = sorted(ORM_TABLES[table] - SQL_TABLES[table])
    assert not only_sql, f"{table}: columns in SQL but not in ORM: {only_sql}"
    assert not only_orm, f"{table}: columns in ORM but not in SQL: {only_orm}"


def test_every_table_is_mapped():
    """``Base.metadata`` and the declarative registry must agree."""
    assert set(Base.metadata.tables) == set(ORM_TABLES)


# =============================================================================
# Canonical scoring spec
# =============================================================================

def test_canonical_thresholds_used_everywhere():
    from app.detection import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS

    assert DEFAULT_THRESHOLDS == {"low": 0.25, "medium": 0.50, "high": 0.75}
    assert DEFAULT_WEIGHTS == {"rule": 0.4, "ml": 0.6}


def test_ml_timeout_is_five_seconds():
    from app.detection import ML_TIMEOUT_SECONDS

    assert ML_TIMEOUT_SECONDS == 5.0


def test_spec_states_the_same_thresholds():
    text = SPEC.read_text()
    assert '"low": 0.25' in text
    assert '"medium": 0.50' in text or '"medium": 0.5' in text
    assert '"high": 0.75' in text


def test_seeded_policy_uses_the_canonical_rule_shape():
    from app.detection import validate_rule

    rules = M.Policy.__table__
    assert rules is not None  # sanity: the model exists

    import json

    sql = (SQL_DIR / "schema-detection-v3.3.sql").read_text()
    start = sql.index("'v1.0'")
    block = sql[start:]
    raw = block[block.index("'[") + 1: block.index("]'::jsonb") + 1]
    parsed = json.loads(raw.replace("'", '"'))
    # strip SQL-only keys and trailing commas are not present in JSON
    for rule in parsed:
        assert validate_rule(rule) is None, rule["name"]


# =============================================================================
# Feature contract (UC-DE-02)
# =============================================================================

def test_six_canonical_features():
    from app.schemas import ALLOWED_FEATURE_FIELDS

    assert set(ALLOWED_FEATURE_FIELDS) == {
        "hour_of_day",
        "fail_count_24h",
        "ip_change_rate_7d",
        "new_device",
        "average_login_interval_seconds",
        "deviation_score",
    }


def test_login_event_outcome_values_match_the_sql_check():
    from app.schemas import LoginEventRequest

    pattern = LoginEventRequest.model_fields["outcome"].metadata[0].pattern
    allowed = set(re.findall(r"[a-z_]+", pattern.strip("^$()")))

    sql = (SQL_DIR / "schema-detection-v3.3.sql").read_text()
    start = sql.index("outcome               TEXT NOT NULL")
    block = sql[start: sql.index("mfa_used", start)]
    db_values = set(re.findall(r"'([a-z_]+)'", block))

    assert allowed == db_values


# =============================================================================
# API paths
# =============================================================================

def test_every_internal_path_in_the_spec_is_implemented():
    from app.main import app

    implemented = {
        r.path for r in app.routes if hasattr(r, "path") and "/internal/" in r.path
    }
    # normalise the {id} placeholders before comparing
    normalised = {p.split("/")[-1].split("{")[0] and p for p in implemented}

    for path in sorted(set(re.findall(r"/api/v1/internal/[a-z\-/]+", SPEC.read_text()))):
        leaf = path.rsplit("/", 1)[-1]
        assert any(p.rsplit("/", 1)[-1] == leaf for p in normalised), path


def test_no_legacy_prefix_in_code():
    """The old ``/internal/v1/`` prefix must not come back."""
    for path in sorted((ROOT / "app").glob("*.py")):
        assert "/internal/v1/" not in path.read_text(), path.name
