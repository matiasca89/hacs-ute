"""Unit tests for add-on calculations without UTE or Home Assistant access."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch


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
