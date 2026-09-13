from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


CORE_APP_DIR = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(CORE_APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_APP_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_foundation_migration_upgrades_seeds_roles_and_downgrades(database_url: str) -> None:
    config = alembic_config(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    expected_tables = {
        "users",
        "roles",
        "user_roles",
        "sessions",
        "login_attempts",
        "pre_auth_transactions",
        "mfa_challenges",
        "outbox_events",
        "enforcement_audits",
        "ip_rate_limits",
    }
    assert expected_tables.issubset(set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        role_codes = {
            row[0]
            for row in connection.execute(text("SELECT code FROM roles ORDER BY code"))
        }
    assert role_codes == {"USER", "SECURITY_ADMIN", "SOC_ANALYST", "SECURITY_MANAGER"}
    assert "deleted_at" in {column["name"] for column in inspect(engine).get_columns("users")}

    command.downgrade(config, "base")
    assert expected_tables.isdisjoint(set(inspect(engine).get_table_names()))
    engine.dispose()
