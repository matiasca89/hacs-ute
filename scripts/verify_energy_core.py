"""Verify against a real *isolated* Core 2026.9+ server, never production.

Run the server on 127.0.0.1:18123 with the configuration below, then:
  python scripts/verify_energy_core.py
Dependencies: homeassistant==2026.9.4 (server), requests and websockets==15.0.1.
Fixture consumption is intentionally synthetic; no UTE account is accessed.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ute_addon"))
from ute_pkg.energy import prepare_state, sync_statistics
from ute_pkg.ha_statistics import statistics_client

BASE = "http://127.0.0.1:18123"


def authenticate() -> str:
    """Onboard only a fresh local fixture instance and return a temporary token."""
    session = requests.Session()
    response = session.get(BASE + "/api/onboarding", timeout=10)
    response.raise_for_status()
    if any(step["step"] == "user" and step["done"] for step in response.json()):
        raise RuntimeError("Verification requires a fresh isolated HA configuration")
    response = session.post(
        BASE + "/api/onboarding/users",
        json={
            "client_id": BASE + "/",
            "name": "UTE verification",
            "username": "ute_verify",
            "password": secrets.token_hex(24),
            "language": "es",
        },
        timeout=30,
    )
    response.raise_for_status()
    code = response.json()["auth_code"]
    response = session.post(
        BASE + "/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": BASE + "/",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    session.headers["Authorization"] = "Bearer " + token
    response = session.get(BASE + "/api/config", timeout=30)
    response.raise_for_status()
    assert response.json()["time_zone"] == "America/Montevideo"
    print("Real isolated Core:", response.json()["version"])
    # The onboarding route appears before startup tasks/Recorder have finished.
    # Do not treat HTTP readiness as readiness to verify queued statistics.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = session.get(BASE + "/api/core/state", timeout=10)
        response.raise_for_status()
        readiness = response.json()
        if readiness.get("state") == "RUNNING" and not readiness.get(
            "recorder_state", {}
        ).get("migration_in_progress", True):
            print("Core RUNNING and Recorder migration complete: OK")
            break
        time.sleep(1)
    else:
        raise RuntimeError("Isolated Core/Recorder did not finish startup")
    return token


def fixture(days):
    return SimpleNamespace(
        fecha_inicial="01-09-2026",
        fecha_final="03-09-2026",
        daily_energy_kwh=days,
        daily_peak_energy_kwh={},
        daily_off_peak_energy_kwh={},
    )


async def verify(token: str):
    async with statistics_client(
        token, BASE.replace("http:", "ws:") + "/api/websocket"
    ) as client:
        http_config = await client.call({"type": "http/config"})
        if http_config.get("active_config_type") == "pending":
            await client.call({"type": "http/config/promote"})
            confirmed = await client.call({"type": "http/config"})
            assert confirmed["pending"] is None and confirmed["stable"]["server_port"] == 18123
        legacy = "ute_legacy:consumo"
        await client.call(
            {
                "type": "recorder/import_statistics",
                "metadata": {
                    "statistic_id": legacy,
                    "source": "ute_legacy",
                    "name": "Legacy fixture",
                    "mean_type": 0,
                    "has_sum": True,
                    "unit_class": "energy",
                    "unit_of_measurement": "kWh",
                },
                "stats": [
                    {"start": "2026-09-01T03:00:00+00:00", "sum": 999, "state": 999}
                ],
            }
        )
        _, state = prepare_state(
            fixture({"2026-09-01": 2, "2026-09-02": 3, "2026-09-03": 0}),
            {},
            "fixture-account",
        )
        await sync_statistics(client.call, state)
        query = {
            "type": "recorder/statistics_during_period",
            "statistic_ids": [state["statistic_id"], legacy],
            "start_time": "2026-09-01T03:00:00+00:00",
            "end_time": "2026-09-04T03:00:00+00:00",
            "period": "day",
            "types": ["sum", "change"],
        }
        rows = await client.call(query)
        assert [row["change"] for row in rows[state["statistic_id"]]] == [2, 3, 0], rows
        assert rows[legacy][0]["sum"] == 999
        await sync_statistics(client.call, state)
        assert await client.call(query) == rows, (
            "Repeated import duplicated consumption"
        )
        _, corrected = prepare_state(
            fixture({"2026-09-01": 1, "2026-09-02": 3, "2026-09-03": 0}),
            state,
            "fixture-account",
        )
        await sync_statistics(client.call, corrected)
        result = await client.call(query)
        assert [row["change"] for row in result[state["statistic_id"]]] == [1, 3, 0], (
            result
        )
        assert result[legacy][0]["sum"] == 999
        metadata = await client.call(
            {"type": "recorder/list_statistic_ids", "statistic_type": "sum"}
        )
        info = next(
            row for row in metadata if row["statistic_id"] == state["statistic_id"]
        )
        assert info["unit_class"] == "energy" and info["has_sum"]
        print(
            "Daily dates, first-day delta, explicit zero, correction, idempotency and legacy preservation: OK"
        )
    async with statistics_client(
        token, BASE.replace("http:", "ws:") + "/api/websocket"
    ) as client:
        await sync_statistics(client.call, corrected)
        _, lost = prepare_state(fixture({"2026-09-01": 1}), {}, "fixture-account")
        try:
            await sync_statistics(client.call, lost)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Lost ledger was allowed to overwrite recorder history"
            )
        print("New connection/restart and lost-ledger fail-closed protection: OK")

        def gap_fixture(days):
            return SimpleNamespace(
                fecha_inicial="01-09-2026",
                fecha_final="12-09-2026",
                daily_energy_kwh=days,
                daily_peak_energy_kwh=None,
                daily_off_peak_energy_kwh=None,
            )

        # Each execution uses its own isolated series; no deletion/reset needed.
        gap_account = "fixture-gap-" + secrets.token_hex(8)
        suffix = {"2026-09-10": 1, "2026-09-11": 2, "2026-09-12": 3}
        _, suffix_state = prepare_state(gap_fixture(suffix), {}, gap_account)
        assert (await sync_statistics(client.call, suffix_state))["status"] == "verified"
        gap_query = {
            "type": "recorder/statistics_during_period",
            "statistic_ids": [suffix_state["statistic_id"]],
            "start_time": "2026-09-01T03:00:00+00:00",
            "end_time": "2026-09-13T03:00:00+00:00",
            "period": "day",
            "types": ["sum", "change"],
        }
        before_gap = await client.call(gap_query)
        _, gap_state = prepare_state(
            gap_fixture({"2026-09-01": 2, "2026-09-03": 4}),
            suffix_state,
            gap_account,
        )
        paused = await sync_statistics(client.call, gap_state)
        assert paused["status"] == "waiting_for_gap", paused
        assert paused["first_missing_date"] == "2026-09-02", paused
        assert await client.call(gap_query) == before_gap, "Gap changed existing history"
        complete_days = {f"2026-09-{day:02d}": 1 for day in range(1, 10)}
        complete_days.update({"2026-09-01": 2, "2026-09-03": 4, **suffix})
        _, recovered = prepare_state(gap_fixture(complete_days), gap_state, gap_account)
        assert (await sync_statistics(client.call, recovered))["status"] == "verified"
        recovered_rows = await client.call(gap_query)
        assert [row["change"] for row in recovered_rows[recovered["statistic_id"]]] == [
            complete_days[key] for key in sorted(complete_days)
        ], recovered_rows
        await sync_statistics(client.call, recovered)
        assert await client.call(gap_query) == recovered_rows
        print("Earlier-date gap preserves existing history, then full recovery/idempotency: OK")


if __name__ == "__main__":
    # A parent may supply a token for a private local lab already onboarded.
    token_file = os.environ.get("UTE_VERIFY_TOKEN_FILE")
    if token_file:
        values = json.loads(Path(token_file).read_text())
        if values.get("base") != BASE:
            raise RuntimeError("Only the isolated loopback instance is allowed")
        token = values["token"]
    else:
        token = authenticate()
    asyncio.run(verify(token))
