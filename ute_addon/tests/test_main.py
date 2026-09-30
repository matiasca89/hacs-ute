"""Unit tests for add-on calculations without UTE or Home Assistant access."""

from __future__ import annotations

import asyncio
import importlib.util
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

MODULE_PATH = Path(__file__).parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("ute_addon_main", MODULE_PATH)
assert SPEC and SPEC.loader
main = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main)


class TestDailyConsumption(unittest.TestCase):
    def test_daily_value_is_the_dated_ute_reading_not_a_monthly_delta(self):
        data = main.UTEConsumoData(
            total_energy_kwh=99, fecha_inicial="01-09-2026", fecha_final="28-09-2026"
        )
        data.daily_energy_kwh = {"2026-09-28": 12.33}
        data.daily_peak_energy_kwh = {"2026-09-28": 2.33}
        data.daily_off_peak_energy_kwh = {"2026-09-28": 10.0}
        daily, state = main.calculate_daily_consumption(
            data, {"last_values": {"total": 100}}
        )
        self.assertEqual(daily, {"peak": 2.33, "off_peak": 10.0, "total": 12.33})
        self.assertEqual(state["daily_date"], "2026-09-28")

    def test_missing_daily_reading_is_unknown_not_a_counter_reset(self):
        data = main.UTEConsumoData(
            total_energy_kwh=99, fecha_inicial="01-09-2026", fecha_final="28-09-2026"
        )
        daily, state = main.calculate_daily_consumption(
            data, {"last_values": {"total": 100}}
        )
        self.assertIsNone(daily["total"])


class TestStateAndPublishing(unittest.TestCase):
    def test_save_and_load_state_are_atomic_and_round_trip(self) -> None:
        state = {"last_date": "2026-08-14", "daily_total": 6.5}
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "data" / "ute_state.json"
            with patch.object(main, "STATE_FILE", state_file):
                main.save_state(state)
                self.assertEqual(main.load_state(), state)
                self.assertFalse(state_file.with_suffix(".tmp").exists())

    def test_load_state_fails_closed_on_corrupt_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            state_file = Path(directory) / "ute_state.json"
            state_file.write_text("not-json", encoding="utf-8")
            with patch.object(main, "STATE_FILE", state_file):
                with self.assertRaises(RuntimeError) as caught:
                    main.load_state()
                self.assertEqual(
                    str(caught.exception),
                    "Unable to load UTE ledger; restore the add-on backup before importing statistics",
                )

    def test_load_state_rejects_json_list_and_null(self) -> None:
        message = (
            "Unable to load UTE ledger; restore the add-on backup before importing statistics"
        )
        for payload in ("[]", "null"):
            with self.subTest(payload=payload):
                with TemporaryDirectory() as directory:
                    state_file = Path(directory) / "ute_state.json"
                    state_file.write_text(payload, encoding="utf-8")
                    with patch.object(main, "STATE_FILE", state_file):
                        with self.assertRaises(RuntimeError) as caught:
                            main.load_state()
                        self.assertEqual(str(caught.exception), message)

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

        self.assertEqual(session.post.call_count, 8)
        urls = [call.args[0] for call in session.post.call_args_list]
        self.assertIn(f"{main.SUPERVISOR_API}/states/sensor.ute_energia_total", urls)
        unavailable = next(
            call
            for call in session.post.call_args_list
            if call.args[0].endswith("ute_energia_fuera_punta")
        )
        self.assertEqual(unavailable.kwargs["json"]["state"], "unavailable")
        for call in session.post.call_args_list:
            self.assertNotIn("state_class", call.kwargs["json"]["attributes"])
        efficiency_call = next(
            call
            for call in session.post.call_args_list
            if call.args[0].endswith("ute_eficiencia")
        )
        self.assertEqual(
            efficiency_call.kwargs["json"]["attributes"]["unit_of_measurement"], "%"
        )
        response.raise_for_status.assert_called()


class TestAddonLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_main_releases_browser_after_each_scrape(self) -> None:
        config = {
            "username": "user",
            "password": "password",
            "account_id": "account",
            "scan_interval": 60,
            "import_statistics": False,
        }
        scraper = MagicMock()
        scraper.get_consumption_data = AsyncMock(
            return_value=main.UTEConsumoData(
                total_energy_kwh=3.0,
                fecha_inicial="01-09-2026",
                fecha_final="28-09-2026",
            )
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


def _recorder_client(imported: list[dict] | None = None):
    if imported is None:
        imported = []
    calls: list[dict] = []

    async def call(message):
        calls.append(message)
        if message["type"] == "recorder/statistics_during_period":
            identifier = message["statistic_ids"][0]
            return {identifier: list(imported)}
        if message["type"] == "recorder/import_statistics":
            imported.clear()
            imported.extend(
                {
                    "start": datetime.fromisoformat(row["start"]).timestamp() * 1000,
                    "sum": row["sum"],
                }
                for row in message["stats"]
            )
            return None
        raise AssertionError(message)

    @asynccontextmanager
    async def client(_token):
        yield SimpleNamespace(call=call)

    return client, calls


class TestStatisticsLogging(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        reading,
        initial_state: dict | None = None,
        imported: list[dict] | None = None,
    ) -> tuple[str, list[dict]]:
        config = {
            "username": "user",
            "password": "password",
            "account_id": "account",
            "scan_interval": 60,
            "import_statistics": True,
        }
        scraper = MagicMock()
        scraper.get_consumption_data = AsyncMock(return_value=reading)
        scraper.close = AsyncMock()
        client, calls = _recorder_client(imported)

        async def stop_after_first_cycle(_: float) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(main, "get_config", return_value=config),
            patch.object(main, "UTEScraper", return_value=scraper),
            patch.object(main, "load_state", return_value=initial_state or {}),
            patch.object(main, "save_state"),
            patch.object(main, "publish_data"),
            patch.object(main, "statistics_client", client),
            patch.object(main.asyncio, "sleep", side_effect=stop_after_first_cycle),
            self.assertLogs(main.LOGGER, level="INFO") as logs,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await main.main()
        return "\n".join(logs.output), calls

    async def test_main_logs_prefix_pending_not_full_sync(self) -> None:
        reading = main.UTEConsumoData(
            total_energy_kwh=7,
            fecha_inicial="01-09-2026",
            fecha_final="04-09-2026",
            daily_energy_kwh={"2026-09-01": 1, "2026-09-03": 5, "2026-09-04": 1},
        )
        text, calls = await self._run(reading)
        imports = [call for call in calls if call["type"] == "recorder/import_statistics"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(len(imports[0]["stats"]), 1)
        self.assertIn(
            "Energy statistics prefix verified; 2 days pending from 2026-09-02",
            text,
        )
        self.assertNotIn("Energy statistics synchronized and verified", text)

    async def test_main_does_not_claim_success_when_no_confirmed_days(self) -> None:
        reading = main.UTEConsumoData(
            total_energy_kwh=None,
            fecha_inicial="01-09-2026",
            fecha_final="28-09-2026",
        )
        text, calls = await self._run(reading)
        self.assertTrue(
            any(call["type"] == "recorder/statistics_during_period" for call in calls)
        )
        self.assertFalse(
            any(call["type"] == "recorder/import_statistics" for call in calls)
        )
        self.assertIn("Energy statistics waiting for confirmed UTE days", text)
        self.assertNotIn("synchronized and verified", text)
        self.assertNotIn("prefix verified", text)

    async def test_main_logs_full_sync_only_when_prefix_is_complete(self) -> None:
        reading = main.UTEConsumoData(
            total_energy_kwh=5,
            fecha_inicial="01-09-2026",
            fecha_final="02-09-2026",
            daily_energy_kwh={"2026-09-01": 2, "2026-09-02": 3},
        )
        text, _calls = await self._run(reading)
        self.assertIn("Energy statistics synchronized and verified", text)
        self.assertNotIn("pending", text)

    async def test_main_logs_gap_pause_not_verified_sync(self) -> None:
        suffix = main.UTEConsumoData(
            total_energy_kwh=6,
            fecha_inicial="10-09-2026",
            fecha_final="12-09-2026",
            daily_energy_kwh={"2026-09-10": 1, "2026-09-11": 2, "2026-09-12": 3},
        )
        _, suffix_state = main.calculate_daily_consumption(suffix, {}, "account")
        imported = [
            {
                "start": datetime.fromisoformat(start).timestamp() * 1000,
                "sum": total,
            }
            for start, total in (
                ("2026-09-10T03:00:00+00:00", 1),
                ("2026-09-11T03:00:00+00:00", 3),
                ("2026-09-12T03:00:00+00:00", 6),
            )
        ]
        preserved = [dict(row) for row in imported]
        reading = main.UTEConsumoData(
            total_energy_kwh=6,
            fecha_inicial="01-09-2026",
            fecha_final="12-09-2026",
            daily_energy_kwh={"2026-09-01": 2, "2026-09-03": 4},
        )
        text, calls = await self._run(
            reading, initial_state=suffix_state, imported=imported
        )
        self.assertIn(
            "Energy statistics paused pending missing date 2026-09-02; 3 recorder rows preserved",
            text,
        )
        self.assertNotIn("synchronized and verified", text)
        self.assertNotIn("prefix verified", text)
        self.assertNotIn("Energy synchronization failed", text)
        self.assertNotIn("Energy synchronization incomplete", text)
        self.assertFalse(
            any(call["type"] == "recorder/import_statistics" for call in calls)
        )
        self.assertEqual(imported, preserved)
