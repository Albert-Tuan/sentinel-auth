"""Tests for app/client_ip.py — canonical IP resolver and proxy-trust validator."""

import os
from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from app.client_ip import (
    get_client_ip,
    validate_proxy_trust_config,
    ProxyTrustConfigurationError,
)


# =============================================================================
# validate_proxy_trust_config() tests
# =============================================================================

class TestValidateProxyTrustConfig:
    """Section 12: configuration tests for validate_proxy_trust_config()."""

    def test_absent_envvar_is_valid(self):
        """A: FORWARDED_ALLOW_IPS absent → safe default (Uvicorn defaults apply)."""
        saved = os.environ.pop("FORWARDED_ALLOW_IPS", None)
        try:
            validate_proxy_trust_config()  # must not raise
        finally:
            if saved is not None:
                os.environ["FORWARDED_ALLOW_IPS"] = saved

    def test_single_trusted_ip_is_valid(self):
        """B: FORWARDED_ALLOW_IPS=127.0.0.1 → accepted."""
        saved = os.environ.get("FORWARDED_ALLOW_IPS")
        os.environ["FORWARDED_ALLOW_IPS"] = "127.0.0.1"
        try:
            validate_proxy_trust_config()  # must not raise
        finally:
            if saved is None:
                os.environ.pop("FORWARDED_ALLOW_IPS", None)
            else:
                os.environ["FORWARDED_ALLOW_IPS"] = saved

    def test_multiple_trusted_ips_valid(self):
        """C: FORWARDED_ALLOW_IPS=10.0.0.10,10.0.0.11 → accepted."""
        saved = os.environ.get("FORWARDED_ALLOW_IPS")
        os.environ["FORWARDED_ALLOW_IPS"] = "10.0.0.10,10.0.0.11"
        try:
            validate_proxy_trust_config()  # must not raise
        finally:
            if saved is None:
                os.environ.pop("FORWARDED_ALLOW_IPS", None)
            else:
                os.environ["FORWARDED_ALLOW_IPS"] = saved

    def test_cidr_block_valid(self):
        """D: FORWARDED_ALLOW_IPS=10.10.0.0/24 → accepted."""
        saved = os.environ.get("FORWARDED_ALLOW_IPS")
        os.environ["FORWARDED_ALLOW_IPS"] = "10.10.0.0/24"
        try:
            validate_proxy_trust_config()  # must not raise
        finally:
            if saved is None:
                os.environ.pop("FORWARDED_ALLOW_IPS", None)
            else:
                os.environ["FORWARDED_ALLOW_IPS"] = saved

    def test_wildcard_star_is_rejected(self):
        """E: FORWARDED_ALLOW_IPS=* → ProxyTrustConfigurationError."""
        saved = os.environ.get("FORWARDED_ALLOW_IPS")
        os.environ["FORWARDED_ALLOW_IPS"] = "*"
        try:
            with pytest.raises(ProxyTrustConfigurationError) as exc_info:
                validate_proxy_trust_config()
            assert "forbidden" in str(exc_info.value).lower()
        finally:
            if saved is None:
                os.environ.pop("FORWARDED_ALLOW_IPS", None)
            else:
                os.environ["FORWARDED_ALLOW_IPS"] = saved

    def test_malformed_ip_rejected(self):
        """F: Malformed IP → ProxyTrustConfigurationError, not silently trusted."""
        saved = os.environ.get("FORWARDED_ALLOW_IPS")
        os.environ["FORWARDED_ALLOW_IPS"] = "not-an-ip"
        try:
            with pytest.raises(ProxyTrustConfigurationError) as exc_info:
                validate_proxy_trust_config()
            assert "not-an-ip" in str(exc_info.value)
        finally:
            if saved is None:
                os.environ.pop("FORWARDED_ALLOW_IPS", None)
            else:
                os.environ["FORWARDED_ALLOW_IPS"] = saved


# =============================================================================
# get_client_ip() tests
# =============================================================================

class TestGetClientIp:
    """Section 9: direct XFF spoof test.

    The canonical resolver must return request.client.host — it does NOT read
    X-Forwarded-For directly.  A direct (unproxied) client that supplies a
    fake X-Forwarded-For must not change the result.
    """

    def _make_request(self, client_host: str, headers: dict | None = None) -> Request:
        """Build a Starlette Request with a mocked client and headers."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [
                (k.encode(), v.encode()) for k, v in (headers or {}).items()
            ],
            "client": (client_host, 12345),
            "server": ("localhost", 8000),
        }
        receive = MagicMock()
        return Request(scope, receive)

    def test_returns_client_host(self):
        """request.client.host is returned when available."""
        req = self._make_request("203.0.113.20")
        assert get_client_ip(req) == "203.0.113.20"

    def test_xff_header_ignored_by_canonical_resolver(self):
        """X-Forwarded-For is not read by the canonical resolver.

        A direct client sends a fake X-Forwarded-For; the resolver must still
        return the socket peer address, not the forged header value.
        """
        req = self._make_request(
            "203.0.113.20",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        # The canonical resolver ignores X-Forwarded-For entirely.
        # It returns the ASGI client address — the real peer.
        assert get_client_ip(req) == "203.0.113.20"
        assert get_client_ip(req) != "1.2.3.4"

    def test_multi_value_xff_header_ignored(self):
        """Multi-hop XFF header is also ignored by the canonical resolver."""
        req = self._make_request(
            "10.0.0.10",
            headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"},
        )
        # Canonical resolver: no XFF parsing
        assert get_client_ip(req) == "10.0.0.10"
        assert get_client_ip(req) not in ("1.1.1.1", "2.2.2.2")

    def test_ipv6_client(self):
        """IPv6 client address is returned as-is."""
        req = self._make_request("2001:db8::1")
        assert get_client_ip(req) == "2001:db8::1"

    def test_ipv6_client_xff_ignored(self):
        """X-Forwarded-For does not affect IPv6 peer address."""
        req = self._make_request(
            "2001:db8::1",
            headers={"X-Forwarded-For": "198.51.100.25"},
        )
        assert get_client_ip(req) == "2001:db8::1"
        assert get_client_ip(req) != "198.51.100.25"

    def test_unknown_when_client_none(self):
        """Returns 'unknown' when request.client is None (unit-test scenarios)."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [],
            "client": None,
            "server": ("localhost", 8000),
        }
        receive = MagicMock()
        req = Request(scope, receive)
        assert get_client_ip(req) == "unknown"
