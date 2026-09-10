"""
Per-IP rate limiting and a global concurrency cap for the MCP endpoint.

This is what stands in place of authentication. The tools are read-only over public
EBAS data served from our own SQLite, so a token would protect the container, not
the data — and the thing actually worth protecting is the container: one Railway
instance running the dashboard's own `/api/*` traffic on the same event loop.

In-process state is sufficient and honest here: one container, one uvicorn process.
If this ever runs replicated, these counters become per-replica and the limit
multiplies by the replica count.

Wrapped around the MCP app only, never around `/api/*`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60.0

# Drop idle IPs periodically: the bookkeeping dict is keyed by caller-controlled
# addresses, so without a sweep it grows without bound.
_SWEEP_EVERY = 500


class RateLimitMiddleware:
    """Sliding-window limit per client address, plus a cap on concurrent requests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int = 60,
        max_concurrent: int = 8,
        queue_timeout: float = 10.0,
    ) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.max_concurrent = max_concurrent
        self.queue_timeout = queue_timeout
        self._hits: dict[str, deque[float]] = {}
        self._since_sweep = 0
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        # uvicorn's --proxy-headers rewrites scope["client"] from X-Forwarded-For, so
        # this is the proxied caller behind Railway and the socket peer locally.
        # Parsing the header here as well would only add a spoofable second source.
        ip = client[0] if client else "unknown"

        retry_after = self._over_limit(ip)
        if retry_after is not None:
            response = JSONResponse(
                {
                    "error": "rate_limited",
                    "message": (
                        f"Over the limit of {self.requests_per_minute} requests per minute "
                        f"for this address. Wait {retry_after}s and retry; batch related "
                        f"questions into fewer calls rather than polling."
                    ),
                    "retry_after_seconds": retry_after,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout)
        except asyncio.TimeoutError:
            response = JSONResponse(
                {
                    "error": "busy",
                    "message": (
                        "The server is at its concurrency limit. Retry shortly; run "
                        "requests sequentially rather than fanning out."
                    ),
                    "retry_after_seconds": 5,
                },
                status_code=503,
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            self._semaphore.release()

    def _over_limit(self, ip: str) -> int | None:
        """Record a hit; return seconds to wait if the caller is over its limit."""
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        hits = self._hits.setdefault(ip, deque())
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.requests_per_minute:
            # The oldest hit in the window is the one that has to age out first.
            # A rejected request is not recorded, so being over the limit cannot
            # extend the lockout indefinitely.
            retry_after = max(1, int(_WINDOW_SECONDS - (now - hits[0])) + 1)
        else:
            hits.append(now)
            retry_after = None

        # After appending, never before: a sweep between the prune and the append
        # would delete this IP's now-empty deque from the dict and leave `hits`
        # orphaned, silently not counting the request.
        self._since_sweep += 1
        if self._since_sweep >= _SWEEP_EVERY:
            self._sweep(cutoff)

        return retry_after

    def _sweep(self, cutoff: float) -> None:
        self._since_sweep = 0
        for ip in [ip for ip, hits in self._hits.items() if not hits or hits[-1] < cutoff]:
            del self._hits[ip]
