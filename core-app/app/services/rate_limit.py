"""Redis-backed authentication throttling; no process-local enforcement state."""

from __future__ import annotations

from typing import Protocol

import redis

from app.core.tokens import context_digest
from app.core.settings import Settings


class AuthenticationRateLimiter(Protocol):
    def allow(self, *, scope: str, source_ip: str, account_identifier: str) -> bool: ...


class RedisAuthenticationRateLimiter:
    """Enforce a fixed window across both source IP and normalized account key."""

    _SCRIPT = """
local ip_count = redis.call('INCR', KEYS[1])
if ip_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local account_count = redis.call('INCR', KEYS[2])
if account_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[2]) end
if ip_count > tonumber(ARGV[1]) or account_count > tonumber(ARGV[1]) then return 0 end
return 1
"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def allow(self, *, scope: str, source_ip: str, account_identifier: str) -> bool:
        ip_key = self._key(scope, "ip", source_ip)
        account_key = self._key(scope, "account", account_identifier.casefold())
        allowed = self._client.eval(
            self._SCRIPT,
            2,
            ip_key,
            account_key,
            self._settings.auth_rate_limit_requests,
            self._settings.auth_rate_limit_window_seconds,
        )
        return bool(allowed)

    def _key(self, scope: str, kind: str, value: str) -> str:
        return f"core-app:auth-rate-limit:{scope}:{kind}:{context_digest(value, self._settings)}"
