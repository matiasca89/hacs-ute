"""Tests for UTE scraper behavior with mocked browser objects."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from ute_pkg import ute_scraper as scraper_module
from ute_pkg.ute_scraper import UTEConnectionError, UTEScraper, UTEScraperError


class FakeContext:
    def __init__(self) -> None:
        self.page = MagicMock()
        self.new_page = AsyncMock(return_value=self.page)
        self.close = AsyncMock()


class TestConsumptionResponse(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_uses_peak_and_off_peak_when_total_is_empty(self) -> None:
        payload = {
            "CONSUMO_ACTUAL": {
                "consumoActualTramoHorario": {
                    "data": {
                        "datasets": [
                            {"label": "Punta", "data": [1.25, None, 2.5]},
                            {"label": "Fuera de Punta", "data": [4.0, 0.75]},
                            {"label": "Total", "data": [None, 0]},
                        ]
                    }
                }
            }
        }
        body = MagicMock()
        body.inner_text = AsyncMock(return_value=json.dumps(payload))
        page = MagicMock()
        page.goto = AsyncMock()
        page.locator.return_value = body

        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765"
        )

        self.assertEqual(result.peak_energy_kwh, 3.75)
        self.assertEqual(result.off_peak_energy_kwh, 4.75)
        self.assertEqual(result.total_energy_kwh, 8.5)
        self.assertEqual(result.efficiency, 55.88)
        self.assertEqual(result.sp_id, "98765")
        self.assertIn("[psId]=98765", page.goto.call_args.args[0])

    async def test_fetch_rejects_invalid_json(self) -> None:
        body = MagicMock()
        body.inner_text = AsyncMock(return_value="not-json")
        page = MagicMock()
        page.goto = AsyncMock()
        page.locator.return_value = body

        with self.assertRaisesRegex(UTEScraperError, "Invalid JSON"):
            await UTEScraper("user", "password", "account")._fetch_consumption_data(
                page, "98765"
            )


class TestAuthenticationRetries(unittest.IsolatedAsyncioTestCase):
    async def test_network_changed_is_retried_as_connection_error(self) -> None:
        page = MagicMock()
        page.goto = AsyncMock(side_effect=Exception("net::ERR_NETWORK_CHANGED"))

        with self.assertRaises(UTEConnectionError):
            await UTEScraper("user", "password", "account")._login(page)

    async def test_connection_failure_recreates_context_before_retry(self) -> None:
        scraper = UTEScraper("user", "password", "account")
        first_context, second_context = FakeContext(), FakeContext()
        scraper._ensure_browser = AsyncMock(return_value=MagicMock())
        scraper._new_context = AsyncMock(side_effect=[first_context, second_context])
        scraper._login = AsyncMock(side_effect=[UTEConnectionError("temporary"), True])

        with patch.object(scraper_module.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            context, page = await scraper._authenticated_page()

        self.assertIs(context, second_context)
        self.assertIs(page, second_context.page)
        first_context.close.assert_awaited_once()
        second_context.close.assert_not_awaited()
        sleep.assert_awaited_once_with(scraper_module.LOGIN_RETRY_DELAYS_SECONDS[0])

    async def test_all_connection_failures_close_every_context(self) -> None:
        scraper = UTEScraper("user", "password", "account")
        contexts = [FakeContext() for _ in range(3)]
        scraper._ensure_browser = AsyncMock(return_value=MagicMock())
        scraper._new_context = AsyncMock(side_effect=contexts)
        scraper._login = AsyncMock(side_effect=UTEConnectionError("offline"))

        with patch.object(scraper_module.asyncio, "sleep", new_callable=AsyncMock):
            with self.assertRaises(UTEConnectionError):
                await scraper._authenticated_page()

        for context in contexts:
            context.close.assert_awaited_once()
