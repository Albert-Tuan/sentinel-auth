"""The ``INET`` column type across both PostgreSQL drivers.

The two drivers the project supports read PostgreSQL's ``INET`` type
differently:

  - ``psycopg2`` returns the address as a ``str``;
  - ``psycopg`` (psycopg 3) returns an ``ipaddress.IPv4Address`` /
    ``IPv6Address`` object.

Which driver is in play is NOT a property of this repository: it depends
on the SQLAlchemy version, because SQLAlchemy 2.1 changed the default
driver of a bare ``postgresql://`` URL from ``psycopg2`` to ``psycopg``.
A deployment that pins SQLAlchemy gets one behaviour, and a deployment
that lets it float gets the other - with no error and no warning
anywhere.

The difference is invisible until a value reaches a validator that expects
text.  ``TrustedDeviceItem.last_ip`` is declared ``Optional[str]``, so
under psycopg 3 the device list raised a Pydantic ``ValidationError`` and
the endpoint answered **500**: the user could trust a device and the
screen could not show it.

``app.models.StrINET`` removes the difference at the source, so the value
is normalised to text on the way out of the database under every driver
and every SQLAlchemy version.

These tests read the value through the **ORM** - a real
``UserTrustedDevice`` row, written and read back - and not through a raw
``SELECT ...::inet``.  A raw query would only prove that the DATABASE
returns a string; it would not prove that the COLUMN TYPE the
application declares returns one, which is the thing that actually broke.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User, UserTrustedDevice

#: The two drivers the project supports.  The bare ``postgresql://`` is
#: deliberately NOT in this list: which driver it resolves to is exactly
#: the thing that changed under SQLAlchemy 2.1, so pinning it would pin
#: the behaviour instead of proving it.
DRIVERS = ("psycopg2", "psycopg")


def _driver_available(driver: str) -> bool:
    """Return True when the named driver can be imported."""
    try:
        if driver == "psycopg2":
            import psycopg2  # noqa: F401
        else:
            import psycopg  # noqa: F401
    except ImportError:  # pragma: no cover - both are hard dependencies
        return False
    return True


def _base_url() -> str:
    """The URL of the disposable Core database, without a driver."""
    url = os.environ.get("CORE_DETECTION_TEST_URL", "").strip()
    if not url:
        return ""
    # Strip the driver, so the test can append the one it wants to prove.
    scheme, _, rest = url.partition("://")
    if not rest:
        return ""
    return f"postgresql://{rest}"


def _url_for(driver: str) -> str:
    return f"postgresql+{driver}://{_base_url().split('://', 1)[1]}"


#: The module skips itself when PostgreSQL is not configured, exactly
#: like the other PostgreSQL modules.  The CI acceptance policy treats a
#: skip as a failure, so the CI provisions the disposable databases
#: before the suite runs.
BASE_URL = _base_url()

requires_postgres = pytest.mark.skipif(
    not BASE_URL,
    reason=(
        "PostgreSQL is not configured, so the INET driver parity was "
        "skipped. Set CORE_DETECTION_TEST_URL to the disposable Core "
        "database to run it."
    ),
)


def _seed_user(session) -> str:
    """Create a user the trusted device can belong to."""
    marker = uuid.uuid4().hex[:12]
    user = User(
        id=uuid.uuid4(),
        username=f"inet_{marker}",
        password_hash="not-a-real-hash",
        email=f"inet_{marker}@example.com",
        status="active",
    )
    session.add(user)
    session.commit()
    return str(user.id)


@pytest.fixture()
def core_session(request):
    """A session on the disposable Core database, for one driver."""
    driver = request.param
    engine = create_engine(_url_for(driver), pool_pre_ping=True)
    maker = sessionmaker(bind=engine)
    session = maker()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_device(session, last_ip) -> UserTrustedDevice:
    """Write a trusted device and read it back through the ORM."""
    user_id = _seed_user(session)
    device = UserTrustedDevice(
        id=uuid.uuid4(),
        user_id=user_id,
        device_fingerprint=f"fp_{uuid.uuid4().hex[:16]}",
        device_name="the INET parity probe",
        last_ip=last_ip,
    )
    session.add(device)
    session.commit()

    # Expire everything so the value is re-read from the DATABASE rather
    # than served from the identity map.  Without this the test would
    # pass even if the column type were broken, because the value would
    # still be the Python object that was written.
    session.expire_all()
    return session.get(UserTrustedDevice, device.id)


# =============================================================================
# The parity itself
# =============================================================================

class TestTheInetColumnIsAStringUnderEveryDriver:
    """``StrINET`` must hand the application a ``str`` under every driver."""

    @requires_postgres
    @pytest.mark.parametrize("core_session", DRIVERS, indirect=True)
    def test_an_ipv4_address_is_read_back_as_a_string(self, core_session):
        device = _make_device(core_session, "203.0.113.77")
        assert isinstance(device.last_ip, str), (
            f"the INET column came back as {type(device.last_ip).__name__}, "
            f"not str"
        )
        assert device.last_ip == "203.0.113.77"

    @requires_postgres
    @pytest.mark.parametrize("core_session", DRIVERS, indirect=True)
    def test_a_null_address_is_read_back_as_none(self, core_session):
        device = _make_device(core_session, None)
        assert device.last_ip is None

    @requires_postgres
    @pytest.mark.parametrize("core_session", DRIVERS, indirect=True)
    def test_an_ipv6_address_is_read_back_as_a_string(self, core_session):
        device = _make_device(core_session, "2001:db8::1")
        assert isinstance(device.last_ip, str)
        assert device.last_ip == "2001:db8::1"

    @requires_postgres
    @pytest.mark.parametrize("core_session", DRIVERS, indirect=True)
    def test_the_value_survives_the_response_model(self, core_session):
        # The reason the column type matters: the Pydantic model declares
        # ``Optional[str]``, and under psycopg 3 the un-normalised value
        # raised a ValidationError here - which the endpoint turned into
        # a 500.
        from app.devices import TrustedDeviceItem

        device = _make_device(core_session, "203.0.113.77")

        item = TrustedDeviceItem.model_validate({
            "id": str(device.id),
            "device_name": device.device_name,
            "device_fingerprint": device.device_fingerprint,
            "last_ip": device.last_ip,
            "last_user_agent": device.last_user_agent,
            "last_used_at": device.last_used_at,
            "expires_at": device.expires_at,
            "created_at": device.created_at,
        })

        assert item.last_ip == "203.0.113.77"

    @requires_postgres
    @pytest.mark.parametrize("core_session", DRIVERS, indirect=True)
    def test_a_null_address_survives_the_response_model(self, core_session):
        from app.devices import TrustedDeviceItem

        device = _make_device(core_session, None)

        item = TrustedDeviceItem.model_validate({
            "id": str(device.id),
            "device_name": device.device_name,
            "device_fingerprint": device.device_fingerprint,
            "last_ip": device.last_ip,
            "last_user_agent": device.last_user_agent,
            "last_used_at": device.last_used_at,
            "expires_at": device.expires_at,
            "created_at": device.created_at,
        })

        assert item.last_ip is None


class TestTheDriverDifferenceIsReal:
    """The parity test must be proving something.

    A test that asserts "the value is a string" passes just as well when
    the column type is BROKEN - as long as the driver happens to be the
    forgiving one.  These tests pin the difference itself, so the parity
    test cannot pass by accident.
    """

    @requires_postgres
    def test_the_two_drivers_really_do_read_inet_differently(self):
        """A PLAIN ``INET`` column is read differently by the two drivers.

        This is the difference ``StrINET`` exists to remove, and it is
        asserted against a column that does NOT use ``StrINET`` - so the
        assertion is about the DRIVERS, not about the application's type.
        """
        from sqlalchemy import Column, MetaData, String, Table, select
        from sqlalchemy.dialects.postgresql import INET

        metadata = MetaData()
        table = Table(
            "inet_driver_parity_probe",
            metadata,
            Column("id", String, primary_key=True),
            Column("addr", INET),
        )

        observed = {}

        for driver in DRIVERS:
            engine = create_engine(_url_for(driver), pool_pre_ping=True)
            try:
                metadata.drop_all(engine)
                metadata.create_all(engine)
                with engine.begin() as connection:
                    connection.execute(
                        table.insert().values(id="1", addr="203.0.113.77")
                    )
                with engine.connect() as connection:
                    value = connection.execute(
                        select(table.c.addr)
                    ).scalar_one()
                observed[driver] = type(value).__name__
            finally:
                engine.dispose()

        # psycopg2 hands back a string; psycopg 3 hands back an
        # ``ipaddress`` object.  If this assertion ever fails, the two
        # drivers have converged - and the parity test above is no longer
        # proving that ``StrINET`` does anything.
        assert observed["psycopg2"] == "str", observed
        assert observed["psycopg"] != "str", observed

    @requires_postgres
    def test_the_plain_column_would_break_the_response_model(self):
        """The un-normalised value really does break the response model.

        This is the defect 20 regression: under psycopg 3, the plain
        column's value raised a Pydantic ``ValidationError``, which the
        endpoint turned into a 500.
        """
        from pydantic import ValidationError

        from app.devices import TrustedDeviceItem

        if not _driver_available("psycopg"):  # pragma: no cover
            pytest.skip("psycopg 3 is not installed")

        import ipaddress

        raw = ipaddress.ip_address("203.0.113.77")

        with pytest.raises(ValidationError):
            TrustedDeviceItem.model_validate({
                "id": str(uuid.uuid4()),
                "device_name": "the probe",
                "device_fingerprint": "fp",
                "last_ip": raw,
                "last_user_agent": None,
                "last_used_at": None,
                "expires_at": None,
                "created_at": None,
            })


class TestTheColumnTypeItself:
    """The declaration, checked without a database."""

    def test_the_declared_column_type_normalises_to_str(self):
        from app.models import StrINET

        # The processor is what does the work, so it is called directly:
        # it must return a ``str`` for every value the two drivers
        # produce.
        processor = StrINET().result_processor(None, None)

        import ipaddress

        assert processor("203.0.113.77") == "203.0.113.77"
        assert processor(ipaddress.ip_address("203.0.113.77")) == "203.0.113.77"
        assert processor(ipaddress.ip_address("2001:db8::1")) == "2001:db8::1"
        assert processor(None) is None

    def test_the_column_uses_the_normalising_type(self):
        from app.models import StrINET, inet_type

        assert isinstance(inet_type(), StrINET)

    def test_the_sqlite_variant_is_still_text(self):
        # The unit tests run on SQLite, so the column has to stay a TEXT
        # there - and it must still be the normalising type, so the
        # SQLite variant cannot hide a broken PostgreSQL one.
        from app.models import StrINET, inet_type

        variant = inet_type()
        assert isinstance(variant, StrINET)

        # The SQLite variant is the TEXT one, so a value read back from
        # SQLite is a plain string.
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        from app.db import Base

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, username, password_hash, email, status, "
                        " admin_mfa_required, detection_mfa_once, "
                        " failed_login_count, created_at, updated_at) "
                        "VALUES (:id, 'probe_user', 'x', "
                        "'probe@example.com', 'active', 0, 0, 0, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid.uuid4())},
                )
                connection.execute(
                    text(
                        "INSERT INTO user_trusted_devices "
                        "(id, user_id, device_fingerprint, last_ip, "
                        " last_used_at, created_at) "
                        "VALUES (:id, (SELECT id FROM users LIMIT 1), "
                        "'fp1', '203.0.113.77', "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid.uuid4())},
                )

            session = sessionmaker(bind=engine)()
            try:
                device = session.query(UserTrustedDevice).one()
                assert device.last_ip == "203.0.113.77"
            finally:
                session.close()
        finally:
            engine.dispose()
