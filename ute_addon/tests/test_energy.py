"""Regression tests for dated Energy data and safe external-statistic imports."""

import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from ute_pkg.energy import (
    build_statistics,
    history_start,
    prepare_state,
    statistic_id_for,
    sync_statistics,
)
from ute_pkg.ute_scraper import UTEConsumoData


def data(days, start="01-09-2026", end="03-09-2026"):
    value = UTEConsumoData(
        total_energy_kwh=sum(days.values()), fecha_inicial=start, fecha_final=end
    )
    value.daily_energy_kwh = days
    value.daily_peak_energy_kwh = {}
    value.daily_off_peak_energy_kwh = {}
    return value


class TestLedger(unittest.TestCase):
    def test_migrates_without_importing_old_sums(self):
        _, state = prepare_state(
            data({"2026-09-01": 2.5}),
            {"daily_total": 99, "last_values": {"total": 1923.68}},
            "account",
        )
        self.assertEqual(state["days"], {"2026-09-01": 2.5})
        self.assertEqual(build_statistics(state)[0]["sum"], 2.5)

    def test_corrections_rebuild_later_sums_and_repeated_scrapes_deduplicate(self):
        first = data({"2026-09-01": 100, "2026-09-02": 4})
        _, state = prepare_state(first, {}, "account")
        _, repeated = prepare_state(first, state, "account")
        self.assertEqual(state, repeated)
        _, corrected = prepare_state(
            data({"2026-09-01": 99, "2026-09-02": 4}), state, "account"
        )
        self.assertEqual([x["sum"] for x in build_statistics(corrected)], [99, 103])

    def test_zero_is_valid_but_missing_day_stops_import_not_zero_filled(self):
        _, state = prepare_state(
            data({"2026-09-01": 0, "2026-09-03": 5}), {}, "account"
        )
        self.assertEqual(len(build_statistics(state)), 1)
        _, state = prepare_state(
            data({"2026-09-02": 2, "2026-09-03": 5}), state, "account"
        )
        self.assertEqual([x["sum"] for x in build_statistics(state)], [0, 2, 7])

    def test_timestamp_is_midnight_montevideo_not_scrape_time(self):
        _, state = prepare_state(data({"2026-09-01": 2}), {}, "account")
        self.assertEqual(
            build_statistics(state)[0]["start"], "2026-09-01T03:00:00+00:00"
        )

    def test_restart_month_boundary_and_outage_history_start(self):
        _, state = prepare_state(
            data({"2026-08-31": 2}, "01-08-2026", "31-08-2026"), {}, "account"
        )
        self.assertEqual(history_start(state, "account"), date(2026, 8, 1))
        daily, state = prepare_state(
            data({"2026-09-01": 3}, "01-09-2026", "01-09-2026"), state, "account"
        )
        self.assertEqual(daily, {"peak": None, "off_peak": None, "total": 3})
        self.assertEqual(state["days"]["2026-08-31"], 2)

    def test_month_rollover_anchors_at_earliest_confirmed_day_not_month_start(self):
        # Requested August period starts on the 1st, but the provider's first
        # confirmed day is the 31st. That absence must not become a permanent gap.
        _, august = prepare_state(
            data({"2026-08-31": 2}, "01-08-2026", "31-08-2026"), {}, "account"
        )
        self.assertEqual(august["start_date"], "2026-08-31")
        self.assertNotIn("2026-08-01", august["days"])
        _, september = prepare_state(
            data({"2026-09-01": 3}, "01-09-2026", "01-09-2026"), august, "account"
        )
        rows = build_statistics(september)
        self.assertEqual([row["sum"] for row in rows], [2, 5])
        self.assertEqual(
            [row["start"] for row in rows],
            ["2026-08-31T03:00:00+00:00", "2026-09-01T03:00:00+00:00"],
        )
        self.assertNotIn("2026-08-01", september["days"])

    def test_fixture_starting_on_aug_31_rolls_into_september_without_filling_aug_1(self):
        _, august = prepare_state(
            data({"2026-08-31": 2}, "31-08-2026", "31-08-2026"), {}, "account"
        )
        _, september = prepare_state(
            data({"2026-09-01": 3}, "01-09-2026", "01-09-2026"), august, "account"
        )
        rows = build_statistics(september)
        self.assertEqual([row["sum"] for row in rows], [2, 5])
        self.assertEqual(rows[0]["start"], "2026-08-31T03:00:00+00:00")
        self.assertEqual(september["start_date"], "2026-08-31")

    def test_saved_phantom_month_start_advances_to_earliest_confirmed_day(self):
        buggy = {
            "schema_version": 2,
            "statistic_id": statistic_id_for("account"),
            "start_date": "2026-08-01",
            "days": {"2026-08-31": 2.0},
            "daily_date": "2026-08-31",
        }
        _, repaired = prepare_state(
            data({}, "01-08-2026", "31-08-2026"), buggy, "account"
        )
        self.assertEqual(repaired["start_date"], "2026-08-31")
        self.assertEqual([row["sum"] for row in build_statistics(repaired)], [2.0])
        self.assertEqual(
            build_statistics(repaired)[0]["start"], "2026-08-31T03:00:00+00:00"
        )
        _, rolled = prepare_state(
            data({"2026-09-01": 3}, "01-09-2026", "01-09-2026"), repaired, "account"
        )
        self.assertEqual([row["sum"] for row in build_statistics(rolled)], [2.0, 5.0])

    def test_empty_v2_ledger_initializes_anchor_from_earliest_new_day(self):
        _, empty = prepare_state(
            data({}, "01-09-2026", "15-09-2026"), {}, "account"
        )
        self.assertEqual(empty["days"], {})
        _, state = prepare_state(
            data({"2026-09-15": 4}, "01-09-2026", "15-09-2026"), empty, "account"
        )
        self.assertEqual(state["start_date"], "2026-09-15")
        self.assertEqual([row["sum"] for row in build_statistics(state)], [4])
        self.assertEqual(
            build_statistics(state)[0]["start"], "2026-09-15T03:00:00+00:00"
        )

    def test_period_start_alone_does_not_move_known_anchor_backward(self):
        _, state = prepare_state(
            data({"2026-09-15": 4}, "15-09-2026", "15-09-2026"), {}, "account"
        )
        _, kept = prepare_state(
            data({"2026-09-16": 1}, "01-09-2026", "16-09-2026"), state, "account"
        )
        self.assertEqual(kept["start_date"], "2026-09-15")
        self.assertNotIn("2026-09-01", kept["days"])
        self.assertEqual([row["sum"] for row in build_statistics(kept)], [4, 5])

    def test_earlier_actual_day_moves_anchor_back_without_zero_fill(self):
        _, state = prepare_state(
            data({"2026-09-15": 4}, "15-09-2026", "15-09-2026"), {}, "account"
        )
        _, moved = prepare_state(
            data({"2026-09-10": 2}, "01-09-2026", "15-09-2026"), state, "account"
        )
        self.assertEqual(moved["start_date"], "2026-09-10")
        self.assertEqual(moved["days"]["2026-09-15"], 4)
        self.assertNotIn("2026-09-01", moved["days"])
        self.assertNotIn("2026-09-11", moved["days"])
        rows = build_statistics(moved)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sum"], 2)
        self.assertEqual(rows[0]["start"], "2026-09-10T03:00:00+00:00")

    def test_account_change_never_copies_another_accounts_ledger(self):
        _, state = prepare_state(data({"2026-09-01": 99}), {}, "account1")
        _, new = prepare_state(data({"2026-09-01": 1}), state, "account2")
        self.assertEqual(new["days"], {"2026-09-01": 1})
        self.assertNotEqual(new["statistic_id"], state["statistic_id"])
        self.assertNotIn("account", new["statistic_id"])

    def test_missing_report_does_not_remove_confirmed_old_day(self):
        _, state = prepare_state(data({"2026-09-01": 2}), {}, "account")
        _, new = prepare_state(data({}), state, "account")
        self.assertEqual(new["days"], state["days"])

    def test_missing_tariff_maps_keep_daily_total(self):
        reading = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 2},
        )
        daily, state = prepare_state(reading, {}, "fixture")
        self.assertEqual(daily, {"peak": None, "off_peak": None, "total": 2})
        self.assertEqual(state["days"], {"2026-09-03": 2.0})
        self.assertIsNone(state["peak_days"].get("2026-09-03"))
        self.assertIsNone(state["off_peak_days"].get("2026-09-03"))

    def test_daily_follows_latest_confirmed_day_not_older_or_empty_response(self):
        reading = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-02": 3, "2026-09-03": 4},
            daily_peak_energy_kwh={"2026-09-03": 1},
            daily_off_peak_energy_kwh={"2026-09-03": 3},
        )
        daily, state = prepare_state(reading, {}, "account")
        self.assertEqual(state["daily_date"], "2026-09-03")
        self.assertEqual(daily, {"peak": 1, "off_peak": 3, "total": 4})
        self.assertEqual(state["peak_days"]["2026-09-03"], 1)
        self.assertEqual(state["off_peak_days"]["2026-09-03"], 3)

        older = data({"2026-09-01": 2}, "01-09-2026", "03-09-2026")
        daily_older, kept = prepare_state(older, state, "account")
        self.assertEqual(kept["daily_date"], "2026-09-03")
        self.assertEqual(daily_older, {"peak": 1, "off_peak": 3, "total": 4})
        self.assertEqual(kept["peak_days"]["2026-09-03"], 1)
        self.assertEqual(kept["days"]["2026-09-01"], 2)

        daily_empty, still = prepare_state(
            data({}, "01-09-2026", "03-09-2026"), kept, "account"
        )
        self.assertEqual(still["daily_date"], "2026-09-03")
        self.assertEqual(daily_empty, {"peak": 1, "off_peak": 3, "total": 4})
        self.assertEqual(still["off_peak_days"]["2026-09-03"], 3)

    def test_corrected_total_drops_conflicting_unrefreshed_tariff(self):
        reading = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 10},
            daily_peak_energy_kwh={"2026-09-03": 4},
            daily_off_peak_energy_kwh={"2026-09-03": 6},
        )
        daily, state = prepare_state(reading, {}, "account")
        self.assertEqual(daily, {"peak": 4, "off_peak": 6, "total": 10})

        corrected = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 12},
        )
        daily_corrected, updated = prepare_state(corrected, state, "account")
        self.assertEqual(daily_corrected["total"], 12)
        self.assertIsNone(daily_corrected["peak"])
        self.assertIsNone(daily_corrected["off_peak"])
        self.assertNotIn("2026-09-03", updated["peak_days"])
        self.assertNotIn("2026-09-03", updated["off_peak_days"])
        self.assertNotEqual(daily_corrected["peak"], 4)
        self.assertNotEqual(daily_corrected["off_peak"], 6)

    def test_refreshed_consistent_tariff_replaces_breakdown_after_correction(self):
        reading = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 10},
            daily_peak_energy_kwh={"2026-09-03": 4},
            daily_off_peak_energy_kwh={"2026-09-03": 6},
        )
        _, state = prepare_state(reading, {}, "account")
        refreshed = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 12},
            daily_peak_energy_kwh={"2026-09-03": 5},
            daily_off_peak_energy_kwh={"2026-09-03": 7},
        )
        daily, updated = prepare_state(refreshed, state, "account")
        self.assertEqual(daily, {"peak": 5, "off_peak": 7, "total": 12})
        self.assertEqual(updated["peak_days"]["2026-09-03"], 5)
        self.assertEqual(updated["off_peak_days"]["2026-09-03"], 7)

    def test_conflicting_tariff_response_is_not_retained_or_fabricated(self):
        reading = UTEConsumoData(
            fecha_inicial="01-09-2026",
            fecha_final="03-09-2026",
            daily_energy_kwh={"2026-09-03": 12},
            daily_peak_energy_kwh={"2026-09-03": 4},
            daily_off_peak_energy_kwh={"2026-09-03": 6},
        )
        daily, state = prepare_state(reading, {}, "account")
        self.assertEqual(daily["total"], 12)
        self.assertIsNone(daily["peak"])
        self.assertIsNone(daily["off_peak"])
        self.assertNotIn("2026-09-03", state["peak_days"])
        self.assertNotIn("2026-09-03", state["off_peak_days"])

    def test_invalid_values_dates_and_future_days_are_rejected(self):
        for days in (
            {"2026-09-01": float("nan")},
            {"2026-09-01": -2},
            {"2026-09-01": True},
            {"2026-09-04": 1},
            {"x": 2},
        ):
            with self.subTest(days=days), self.assertRaises(ValueError):
                prepare_state(data(days), {}, "account")


class TestStatisticsSync(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _, self.state = prepare_state(
            data({"2026-09-01": 2, "2026-09-02": 3}), {}, "account"
        )
        self.calls = []
        self.imported = []

    async def call(self, message):
        self.calls.append(message)
        if message["type"] == "recorder/statistics_during_period":
            return {self.state["statistic_id"]: self.imported}
        if message["type"] == "recorder/import_statistics":
            self.imported = [
                {
                    "start": datetime.fromisoformat(x["start"]).timestamp() * 1000,
                    "sum": x["sum"],
                }
                for x in message["stats"]
            ]
            return None
        raise AssertionError(message)

    async def test_import_has_modern_metadata_and_verifies_exact_rows(self):
        await sync_statistics(self.call, self.state)
        imports = [x for x in self.calls if x["type"] == "recorder/import_statistics"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["metadata"]["unit_class"], "energy")
        self.assertEqual(imports[0]["metadata"]["mean_type"], 0)
        self.assertEqual(imports[0]["metadata"]["source"], "ute_consumo")
        self.assertEqual(
            imports[0]["metadata"]["statistic_id"], self.state["statistic_id"]
        )
        self.assertEqual(self.calls[-1]["type"], "recorder/statistics_during_period")

    async def test_identical_existing_rows_skip_import(self):
        await sync_statistics(self.call, self.state)
        self.calls = []
        await sync_statistics(self.call, self.state)
        self.assertFalse(
            any(x["type"] == "recorder/import_statistics" for x in self.calls)
        )

    async def test_restored_or_lost_ledger_cannot_truncate_existing_history(self):
        self.imported = [
            {
                "start": datetime.fromisoformat("2026-08-01T03:00:00+00:00").timestamp()
                * 1000,
                "sum": 100,
            }
        ]
        with self.assertRaisesRegex(ValueError, "ledger"):
            await sync_statistics(self.call, self.state)
        self.assertFalse(
            any(x["type"] == "recorder/import_statistics" for x in self.calls)
        )

    async def test_queued_import_without_readback_is_not_success(self):
        async def call(message):
            self.calls.append(message)
            return (
                {self.state["statistic_id"]: []}
                if message["type"] == "recorder/statistics_during_period"
                else None
            )

        with patch("ute_pkg.energy.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaisesRegex(RuntimeError, "verified"):
                await sync_statistics(call, self.state)

    async def test_empty_days_never_write(self):
        self.state["days"] = {}
        result = await sync_statistics(self.call, self.state)
        reads = [
            call
            for call in self.calls
            if call["type"] == "recorder/statistics_during_period"
        ]
        writes = [
            call for call in self.calls if call["type"] == "recorder/import_statistics"
        ]
        self.assertEqual(len(reads), 1)
        self.assertEqual(writes, [])
        self.assertEqual(
            result,
            {
                "status": "waiting",
                "imported_days": 0,
                "pending_days": 0,
                "first_missing_date": None,
            },
        )

    async def test_empty_ledger_with_recorder_history_refuses_write(self):
        self.state["days"] = {}
        self.imported = [
            {
                "start": datetime.fromisoformat("2026-09-01T03:00:00+00:00").timestamp()
                * 1000,
                "sum": 2,
            }
        ]
        with self.assertRaisesRegex(ValueError, "ledger"):
            await sync_statistics(self.call, self.state)
        self.assertTrue(
            any(call["type"] == "recorder/statistics_during_period" for call in self.calls)
        )
        self.assertFalse(
            any(call["type"] == "recorder/import_statistics" for call in self.calls)
        )

    async def test_internal_gap_imports_only_prefix_and_reports_pending(self):
        _, state = prepare_state(
            data(
                {"2026-09-01": 1, "2026-09-03": 5, "2026-09-04": 1},
                "01-09-2026",
                "04-09-2026",
            ),
            {},
            "account",
        )
        result = await sync_statistics(self.call, state)
        imports = [
            call for call in self.calls if call["type"] == "recorder/import_statistics"
        ]
        self.assertEqual(len(imports), 1)
        self.assertEqual([row["sum"] for row in imports[0]["stats"]], [1])
        self.assertEqual(imports[0]["stats"][0]["start"], "2026-09-01T03:00:00+00:00")
        self.assertEqual(
            result,
            {
                "status": "pending",
                "imported_days": 1,
                "pending_days": 2,
                "first_missing_date": "2026-09-02",
            },
        )

    async def test_complete_import_reports_verified_without_pending(self):
        result = await sync_statistics(self.call, self.state)
        self.assertEqual(
            result,
            {
                "status": "verified",
                "imported_days": 2,
                "pending_days": 0,
                "first_missing_date": None,
            },
        )

    async def test_known_suffix_with_earlier_gap_waits_without_writes(self):
        """Known 10..12 plus an earlier hole must not be treated as a lost ledger."""
        _, suffix = prepare_state(
            data(
                {"2026-09-10": 1, "2026-09-11": 2, "2026-09-12": 3},
                "10-09-2026",
                "12-09-2026",
            ),
            {},
            "account",
        )
        verified = await sync_statistics(self.call, suffix)
        self.assertEqual(verified["status"], "verified")
        self.assertEqual([row["sum"] for row in self.imported], [1, 3, 6])
        preserved = [dict(row) for row in self.imported]
        self.calls.clear()

        _, gapped = prepare_state(
            data({"2026-09-01": 2, "2026-09-03": 4}, "01-09-2026", "12-09-2026"),
            suffix,
            "account",
        )
        self.assertEqual(gapped["start_date"], "2026-09-01")
        self.assertEqual(
            [row["start"] for row in build_statistics(gapped)],
            ["2026-09-01T03:00:00+00:00"],
        )
        paused = await sync_statistics(self.call, gapped)
        self.assertEqual(
            paused,
            {
                "status": "waiting_for_gap",
                "imported_days": 0,
                "pending_days": 5,
                "first_missing_date": "2026-09-02",
                "preserved_days": 3,
            },
        )
        self.assertFalse(
            any(call["type"] == "recorder/import_statistics" for call in self.calls)
        )
        self.assertEqual(self.imported, preserved)

    async def test_filled_gap_rebuilds_known_suffix_sums_and_is_idempotent(self):
        _, suffix = prepare_state(
            data(
                {"2026-09-10": 1, "2026-09-11": 2, "2026-09-12": 3},
                "10-09-2026",
                "12-09-2026",
            ),
            {},
            "account",
        )
        await sync_statistics(self.call, suffix)
        _, gapped = prepare_state(
            data({"2026-09-01": 2, "2026-09-03": 4}, "01-09-2026", "12-09-2026"),
            suffix,
            "account",
        )
        paused = await sync_statistics(self.call, gapped)
        self.assertEqual(paused["status"], "waiting_for_gap")
        self.calls.clear()

        complete = {f"2026-09-{day:02d}": 1 for day in range(1, 10)}
        complete.update(
            {
                "2026-09-01": 2,
                "2026-09-03": 4,
                "2026-09-10": 1,
                "2026-09-11": 2,
                "2026-09-12": 3,
            }
        )
        _, recovered = prepare_state(
            data(complete, "01-09-2026", "12-09-2026"), gapped, "account"
        )
        result = await sync_statistics(self.call, recovered)
        total = 0.0
        expected_sums = []
        for key in sorted(complete):
            total = round(total + complete[key], 2)
            expected_sums.append(total)
        imports = [
            call for call in self.calls if call["type"] == "recorder/import_statistics"
        ]
        self.assertEqual(len(imports), 1)
        self.assertEqual([row["sum"] for row in imports[0]["stats"]], expected_sums)
        self.assertEqual([row["sum"] for row in self.imported], expected_sums)
        self.assertNotEqual(expected_sums[-3:], [1, 3, 6])
        self.assertEqual(
            result,
            {
                "status": "verified",
                "imported_days": 12,
                "pending_days": 0,
                "first_missing_date": None,
            },
        )
        self.calls.clear()
        again = await sync_statistics(self.call, recovered)
        self.assertEqual(again["status"], "verified")
        self.assertFalse(
            any(call["type"] == "recorder/import_statistics" for call in self.calls)
        )
        self.assertEqual([row["sum"] for row in self.imported], expected_sums)

    async def test_recorder_date_absent_from_full_ledger_still_raises(self):
        _, suffix = prepare_state(
            data(
                {"2026-09-10": 1, "2026-09-11": 2, "2026-09-12": 3},
                "10-09-2026",
                "12-09-2026",
            ),
            {},
            "account",
        )
        await sync_statistics(self.call, suffix)
        _, gapped = prepare_state(
            data({"2026-09-01": 2, "2026-09-03": 4}, "01-09-2026", "12-09-2026"),
            suffix,
            "account",
        )
        cases = {
            "date not in ledger": {
                "start": datetime.fromisoformat("2026-09-09T03:00:00+00:00").timestamp()
                * 1000,
                "sum": 9,
            },
            "known date off local midnight": {
                "start": datetime.fromisoformat("2026-09-10T04:00:00+00:00").timestamp()
                * 1000,
                "sum": 1,
            },
        }
        for name, extra in cases.items():
            with self.subTest(name=name):
                self.calls.clear()
                self.imported = [
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
                if name == "known date off local midnight":
                    self.imported[0] = extra
                else:
                    self.imported.append(extra)
                preserved = [dict(row) for row in self.imported]
                with self.assertRaisesRegex(ValueError, "ledger"):
                    await sync_statistics(self.call, gapped)
                self.assertFalse(
                    any(
                        call["type"] == "recorder/import_statistics"
                        for call in self.calls
                    )
                )
                self.assertEqual(self.imported, preserved)


if __name__ == "__main__":
    unittest.main()
