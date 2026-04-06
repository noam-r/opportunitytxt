"""Caching infrastructure for opportunity_txt.

Provides:
- CacheProtocol — generic injectable cache interface (bytes-oriented)
- NullCache     — no-op default implementation
- FileCache     — file-based JSON cache with TTL (optional adapter)
- Cache         — alias for FileCache (backward compatibility)
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

DEFAULT_CACHE_DIR = Path(".cache")
DEFAULT_TTL_SECONDS = 6 * 3600  # 6 hours


# ---------------------------------------------------------------------------
# Public protocol — external callers inject this
# ---------------------------------------------------------------------------

@runtime_checkable
class CacheProtocol(Protocol):
    """Generic cache interface.  Caller provides the key."""

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...


# ---------------------------------------------------------------------------
# Built-in implementations
# ---------------------------------------------------------------------------

class NullCache:
    """No-op cache — all gets miss, all sets are discarded."""

    def get(self, key: str) -> bytes | None:
        return None

    def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        pass


class FileCache:
    """File-based JSON cache with TTL.

    Implements CacheProtocol for external callers and also provides the
    legacy two-argument get/put interface used internally by the collector.
    """

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        enabled: bool = True,
    ):
        self._dir = cache_dir
        self._ttl = ttl_seconds
        self._enabled = enabled
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    # -- CacheProtocol interface (key provided by caller) --

    def get(self, key: str, variables: dict[str, Any] | None = None) -> Any | None:
        """Get a cached value.

        Supports both CacheProtocol (single key string) and legacy collector
        usage (query + variables dict).
        """
        if not self._enabled:
            return None
        if variables is not None:
            # Legacy collector call: key is query, second arg is variables
            resolved_key = self._make_key(key, variables)
        else:
            resolved_key = key
        path = self._dir / f"{resolved_key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - data.get("ts", 0) > self._ttl:
            path.unlink(missing_ok=True)
            return None
        return data.get("payload")

    def set(self, key: str, value: bytes, ttl_seconds: int = 0) -> None:
        """CacheProtocol.set — store raw bytes."""
        if not self._enabled:
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps({
            "ts": time.time(),
            "payload": json.loads(value) if isinstance(value, (bytes, str)) else value,
        }))

    def put(self, query: str, variables: dict[str, Any], payload: Any) -> None:
        """Legacy collector interface — kept for internal compatibility."""
        if not self._enabled:
            return
        resolved_key = self._make_key(query, variables)
        path = self._dir / f"{resolved_key}.json"
        path.write_text(json.dumps({"ts": time.time(), "payload": payload}))

    @staticmethod
    def _make_key(query: str, variables: dict[str, Any]) -> str:
        raw = json.dumps({"q": query, "v": variables}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


# Backward-compatible alias
Cache = FileCache
