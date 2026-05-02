"""Self-register this service with the BE dynamic reverse proxy.

See docs/dyn-proxy-downstream.md. Flow:
1. Expose GET /api/dev/ping → "pong" (handled in api/app.py).
2. On startup, POST /api/v1/proxy/register to BE with our advertise addr.
3. Re-register every PROXY_KEEPALIVE_SEC; same name overwrites, also self-heals
   when BE restarts and loses its in-memory registry.
4. On shutdown, POST /api/v1/proxy/detach.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from config import (
    BE_BASE_URL,
    PROXY_ADVERTISE_ADDR,
    PROXY_KEEPALIVE_SEC,
    PROXY_NAME,
)

logger = logging.getLogger(__name__)


async def _register(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.post(
            f"{BE_BASE_URL}/api/v1/proxy/register",
            json={"name": PROXY_NAME, "addr": PROXY_ADVERTISE_ADDR},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("proxy register failed: %s", e)
        return False
    if r.status_code != 200:
        logger.warning("proxy register non-200: %s %s", r.status_code, r.text)
        return False
    logger.info("proxy register ok: %s", r.json())
    return True


async def _detach(client: httpx.AsyncClient) -> None:
    try:
        await client.post(
            f"{BE_BASE_URL}/api/v1/proxy/detach",
            json={"name": PROXY_NAME},
            timeout=5.0,
        )
    except httpx.HTTPError as e:
        logger.warning("proxy detach failed: %s", e)


async def keepalive_loop() -> None:
    """Re-register on a fixed cadence. Covers BE restarts and transient errors."""
    async with httpx.AsyncClient() as client:
        await _register(client)
        try:
            while True:
                await asyncio.sleep(PROXY_KEEPALIVE_SEC)
                await _register(client)
        except asyncio.CancelledError:
            await _detach(client)
            raise
