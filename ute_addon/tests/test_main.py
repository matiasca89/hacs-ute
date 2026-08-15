"""Unit tests for add-on calculations without UTE or Home Assistant access."""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


MODULE_PATH = Path(__file__).parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("ute_addon_main", MODULE_PATH)
assert SPEC and SPEC.loader
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


class TestDailyConsumption(unittest.TestCase):
    def test_daily_delta_handles_normal_and_month_reset(self) -> None:
        self.assertEqual(main._daily_delta(18.5, 11.25), 7.25)
        self.assertEqual(main._daily_delta(1.5, 300.0), 1.5)
        self.assertIsNone(main._daily_delta(None, 3.0))

    def test_calculate_daily_consumption_preserves_same_day_value(self) -> None:
        data = main.UTEConsumoData(10.0, 20.0, 30.0)
        state = {
            "last_date": "2026-08-14",
            "last_values": {"peak": 9.0, "off_peak": 19.0, "total": 28.0},
            "daily_peak": 1.0,
            "daily_off_peak": 1.0,
            "daily_total": 2.0,
        }
        with patch.object(main, "datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 8, 14, tzinfo=main.URUGUAY_TZ)
            daily, new_state = main.calculate_daily_consumption(data, state)

        self.assertEqual(daily, {"peak": 1.0, "off_peak": 1.0, "total": 2.0})
        self.assertEqual(new_state["last_values"]["total"], 30.0)

    def test_calculate_daily_consumption_calculates_new_day_delta(self) -> None:
        data = main.UTEConsumoData(12.0, 23.0, 35.0)
        state = {
            "last_date": "2026-08-13",
            "last_values": {"peak": 9.0, "off_peak": 20.0, "total": 29.0},
        }
        with patch.object(main, "datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 8, 14, tzinfo=main.URUGUAY_TZ)
            daily, _ = main.calculate_daily_consumption(data, state)

        self.assertEqual(daily, {"peak": 3.0, "off_peak": 3.0, "total": 6.0})


class TestStateAndPublishing(unittest.TestCase):
    def test_save_and_load_state_are_atomic_and_round_trip(self) -> None:
        state = {"last_date": "2026-08-14", "daily_total": 6.5}
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "data" / "ute_state.json"
            with patch.object(main, "STATE_FILE", state_file):
                main.save_state(state)
                self.assertEqual(main.load_state(), state)
                self.assertFalse(state_file.with_suffix(".tmp").exists())

    def test_load_state_recovers_from_invalid_json(self) -> None:
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "ute_state.json"
            state_file.write_text("not-json", encoding="utf-8")
            with patch.object(main, "STATE_FILE", state_file):
                self.assertEqual(main.load_state(), {})

    def test_publish_data_emits_only_available_measurements(self) -> None:
        session = MagicMock()
        response = MagicMock()
        session.post.return_value = response
        data = main.UTEConsumoData(
            peak_energy_kwh=1.0,
            total_energy_kwh=3.0,
            efficiency=66.67,
            fecha_inicial="01-08-2026",
            fecha_final="13-08-2026",
        )

        main.publish_data(session, data, {"peak": None, "off_peak": 2.0, "total": 3.0})

        self.assertEqual(session.post.call_count, 6)
        urls = [call.args[0] for call in session.post.call_args_list]
        self.assertIn(f"{main.SUPERVISOR_API}/states/sensor.ute_energia_total", urls)
        self.assertNotIn(f"{main.SUPERVISOR_API}/states/sensor.ute_energia_fuera_punta", urls)
        efficiency_call = next(
            call for call in session.post.call_args_list if call.args[0].endswith("ute_eficiencia")
        )
        self.assertEqual(efficiency_call.kwargs["json"]["attributes"]["unit_of_measurement"], "%")
        response.raise_for_status.assert_called()


class TestAddonLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_main_releases_browser_after_each_scrape(self) -> None:
        config = {
            "username": "user",
            "password": "password",
            "account_id": "account",
            "scan_interval": 60,
        }
        scraper = MagicMock()
        scraper.get_consumption_data = AsyncMock(
            return_value=main.UTEConsumoData(total_energy_kwh=3.0)
        )
        scraper.close = AsyncMock()

        async def stop_after_first_cycle(_: float) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(main, "get_config", return_value=config),
            patch.object(main, "UTEScraper", return_value=scraper),
            patch.object(main, "load_state", return_value={}),
            patch.object(main, "save_state"),
            patch.object(main, "publish_data"),
            patch.object(main.asyncio, "sleep", side_effect=stop_after_first_cycle),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await main.main()

        # Once after the scrape and once while shutting down.
        self.assertEqual(scraper.close.await_count, 2)
