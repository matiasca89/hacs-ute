"""Small authenticated client for the supported Supervisor/Core WebSocket API."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from websockets.asyncio.client import connect

SUPERVISOR_WEBSOCKET = "ws://supervisor/core/websocket"


class HAStatisticsClient:
    """Serialize requests on a short-lived authenticated connection."""

    def __init__(self, socket: Any) -> None:
        self.socket = socket
        self.message_id = 0

    async def call(self, message: dict[str, Any]) -> Any:
        self.message_id += 1
        identifier = self.message_id
        await self.socket.send(
            json.dumps({**message, "id": identifier}, allow_nan=False)
        )
        while True:
            result = json.loads(await asyncio.wait_for(self.socket.recv(), timeout=30))
            if result.get("id") != identifier:
                continue
            if result.get("success") is not True:
                # Codes are useful; provider messages can contain sensitive identifiers.
                raise RuntimeError(
                    f"HA statistics command rejected: {result.get('error', {}).get('code', 'unknown')}"
                )
            return result.get("result")


@asynccontextmanager
async def statistics_client(token: str, url: str = SUPERVISOR_WEBSOCKET):
    """Authenticate via the Supervisor token; no HA password/config file edits."""
    if not token:
        raise ValueError("SUPERVISOR_TOKEN is required to import Energy statistics")
    async with connect(
        url, open_timeout=15, close_timeout=5, max_size=4 * 1024 * 1024
    ) as socket:
        greeting = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if greeting.get("type") != "auth_required":
            raise RuntimeError("Unexpected HA statistics authentication greeting")
        await socket.send(json.dumps({"type": "auth", "access_token": token}))
        authenticated = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
        if authenticated.get("type") != "auth_ok":
            raise RuntimeError("HA statistics authentication failed")
        yield HAStatisticsClient(socket)
