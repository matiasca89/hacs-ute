"""Fechas locales y curva diaria real del portal UTE. Sin credenciales."""
from __future__ import annotations

import json
import logging
import unittest
from datetime import date, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from ute_pkg import ute_scraper as scraper_module
from ute_pkg.ute_scraper import UTEConsumoData, UTEScraper, UTEScraperError

UY = ZoneInfo("America/Montevideo")
MISSING = object()


def _tramo(
    label: str | None,
    punta=MISSING,
    fuera=MISSING,
    total=MISSING,
    energia=MISSING,
    info: dict | None | object = MISSING,
) -> dict:
    datasets = []
    if punta is not MISSING:
        datasets.append({"label": "Punta", "data": punta})
    if fuera is not MISSING:
        datasets.append({"label": "Fuera de Punta", "data": fuera})
    if total is not MISSING:
        datasets.append({"label": "Total", "data": total})
    chart: dict = {"data": {"datasets": datasets}}
    if label is not None:
        chart["data"]["labels"] = [label]
    consumo: dict = {"consumoActualTramoHorario": chart}
    if energia is not MISSING:
        consumo["consumoActual"] = {
            "data": {
                "labels": ["Consumo Actual"],
                "datasets": [
                    {"label": "Energia Activa (kWh)", "data": energia},
                    {"label": "Energia Reactiva (kVArh)", "data": [0.0]},
                ],
            }
        }
    if info is not MISSING:
        consumo["infoTramoHorario"] = [info] if info is not None else []
    return {"CONSUMO_ACTUAL": consumo}


def _page(payload: dict | str) -> MagicMock:
    body = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    body.inner_text = AsyncMock(return_value=text)
    page = MagicMock()
    page.goto = AsyncMock()
    page.locator.return_value = body
    return page


def _urls(page: MagicMock) -> list[str]:
    return [call.args[0] for call in page.goto.await_args_list]


class FrozenDateTime(datetime):
    """Reloj inyectable. datetime.now del tipo C no se puede parchear."""

    current = datetime(2026, 1, 1, tzinfo=UY)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current
        return cls.current.astimezone(tz)


def _freeze(moment: datetime):
    FrozenDateTime.current = moment
    return patch.object(scraper_module, "datetime", FrozenDateTime)


class TestRequestWindow(unittest.IsolatedAsyncioTestCase):
    async def _requested(self, moment: datetime) -> str:
        page = _page(_tramo(None, punta=[1.0], fuera=[2.0]))
        with _freeze(moment):
            await UTEScraper("user", "password", "account")._fetch_consumption_data(
                page, "98765"
            )
        self.assertEqual(page.goto.await_count, 1)
        return page.goto.await_args.args[0]

    async def test_evening_uruguay_uses_previous_local_day_not_utc(self) -> None:
        # 22:00 UY del 28/09 es 01:00 UTC del 29/09. UTC-1 día pediría el 28.
        url = await self._requested(datetime(2026, 9, 28, 22, 0, tzinfo=UY))
        self.assertIn("[fechaInicial]=01-09-2026", url)
        self.assertIn("[fechaFinal]=27-09-2026", url)
        self.assertNotIn("[fechaFinal]=28-09-2026", url)

    async def test_midnight_month_boundary_starts_previous_month(self) -> None:
        url = await self._requested(datetime(2026, 9, 1, 0, 0, tzinfo=UY))
        self.assertIn("[fechaInicial]=01-08-2026", url)
        self.assertIn("[fechaFinal]=31-08-2026", url)

    async def test_evening_first_of_month_does_not_follow_utc_into_new_month(self) -> None:
        url = await self._requested(datetime(2026, 9, 1, 22, 0, tzinfo=UY))
        self.assertIn("[fechaInicial]=01-08-2026", url)
        self.assertIn("[fechaFinal]=31-08-2026", url)
        self.assertNotIn("[fechaFinal]=01-09-2026", url)

    async def test_midnight_year_boundary_uses_previous_december(self) -> None:
        url = await self._requested(datetime(2027, 1, 1, 0, 0, tzinfo=UY))
        self.assertIn("[fechaInicial]=01-12-2026", url)
        self.assertIn("[fechaFinal]=31-12-2026", url)

    async def test_evening_new_year_eve_does_not_follow_utc_into_january(self) -> None:
        url = await self._requested(datetime(2026, 12, 31, 22, 0, tzinfo=UY))
        self.assertIn("[fechaInicial]=01-12-2026", url)
        self.assertIn("[fechaFinal]=30-12-2026", url)
        self.assertNotIn("[fechaFinal]=31-12-2026", url)

    async def test_explicit_range_overrides_clock_and_logs_no_identifiers(self) -> None:
        page = _page(_tramo("01-09-2026 a 02-09-2026 (DOBLE17)", punta=[1.0], fuera=[1.0]))
        scraper = UTEScraper("user", "secret-password", "account-99")
        with self.assertLogs(scraper_module.__name__, level="DEBUG") as captured:
            await scraper._fetch_consumption_data(
                page, "98765", date(2026, 9, 1), date(2026, 9, 2)
            )
        url = page.goto.await_args.args[0]
        self.assertIn("[fechaInicial]=01-09-2026", url)
        self.assertIn("[fechaFinal]=02-09-2026", url)
        joined = "\n".join(captured.output)
        self.assertNotIn("98765", joined)
        self.assertNotIn("secret-password", joined)
        self.assertNotIn("account-99", joined)


class TestMonthlyAggregate(unittest.IsolatedAsyncioTestCase):
    async def test_range_label_is_not_exploded_into_daily_dates(self) -> None:
        page = _page(
            _tramo(
                "01-09-2026 a 28-09-2026 (DOBLE17)",
                punta=[40.0],
                fuera=[127.34],
                energia=[167.34],
            )
        )
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 1), date(2026, 9, 28)
        )
        self.assertEqual(result.peak_energy_kwh, 40.0)
        self.assertEqual(result.off_peak_energy_kwh, 127.34)
        self.assertEqual(result.total_energy_kwh, 167.34)
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.daily_peak_energy_kwh)
        self.assertIsNone(result.daily_off_peak_energy_kwh)
        self.assertEqual(result.fecha_inicial, "01-09-2026")
        self.assertEqual(result.fecha_final, "28-09-2026")

    async def test_missing_tariff_series_is_none_not_zero(self) -> None:
        page = _page(_tramo("01-09-2026 a 02-09-2026 (DOBLE17)", fuera=[4.5]))
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 1), date(2026, 9, 2)
        )
        self.assertIsNone(result.peak_energy_kwh)
        self.assertEqual(result.off_peak_energy_kwh, 4.5)
        self.assertIsNone(result.total_energy_kwh)
        self.assertIsNone(result.efficiency)
        self.assertEqual(result.daily_energy_kwh, {})

    async def test_real_zero_monthly_tariff_is_kept(self) -> None:
        page = _page(_tramo("01-09-2026 a 02-09-2026 (DOBLE17)", punta=[0.0], fuera=[0.0]))
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 1), date(2026, 9, 2)
        )
        self.assertEqual(result.peak_energy_kwh, 0.0)
        self.assertEqual(result.off_peak_energy_kwh, 0.0)
        self.assertEqual(result.total_energy_kwh, 0.0)

    async def test_new_fields_keep_positional_compatibility(self) -> None:
        first = UTEConsumoData(1.0, 2.0, 3.0)
        second = UTEConsumoData()
        first.daily_energy_kwh["2026-09-01"] = 1.0
        self.assertEqual(second.daily_energy_kwh, {})
        self.assertIsNone(first.daily_peak_energy_kwh)
        self.assertIsNone(first.daily_off_peak_energy_kwh)
        self.assertEqual(first.peak_energy_kwh, 1.0)


class TestOneDayAggregation(unittest.IsolatedAsyncioTestCase):
    async def test_matching_single_day_label_records_real_tariff_values(self) -> None:
        page = _page(
            _tramo(
                "28-09-2026 a 28-09-2026 (DOBLE17)",
                punta=[1.5],
                fuera=[2.25],
                info={"inicio": "28-09-2026", "fin": "28-09-2026", "tipo": "DOBLE", "tarifa": "DOBLE17"},
            )
        )
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertIn("[fechaInicial]=28-09-2026", page.goto.await_args.args[0])
        self.assertIn("[fechaFinal]=28-09-2026", page.goto.await_args.args[0])
        self.assertEqual(result.daily_energy_kwh, {"2026-09-28": 3.75})
        self.assertEqual(result.daily_peak_energy_kwh, {"2026-09-28": 1.5})
        self.assertEqual(result.daily_off_peak_energy_kwh, {"2026-09-28": 2.25})
        self.assertEqual(result.peak_energy_kwh, 1.5)
        self.assertEqual(result.off_peak_energy_kwh, 2.25)

    async def test_energia_activa_is_daily_total_when_present(self) -> None:
        page = _page(
            _tramo(
                "28-09-2026 a 28-09-2026 (DOBLE17)",
                punta=[1.0],
                fuera=[2.0],
                energia=[3.4],
            )
        )
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertEqual(result.daily_energy_kwh, {"2026-09-28": 3.4})
        self.assertEqual(result.total_energy_kwh, 3.4)

    async def test_real_zero_day_is_stored(self) -> None:
        page = _page(
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[0.0], fuera=[0.0], energia=[0.0])
        )
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertEqual(result.daily_energy_kwh, {"2026-09-28": 0.0})
        self.assertEqual(result.daily_peak_energy_kwh, {"2026-09-28": 0.0})
        self.assertEqual(result.daily_off_peak_energy_kwh, {"2026-09-28": 0.0})

    async def test_labels_absent_do_not_invent_a_day(self) -> None:
        page = _page(_tramo(None, punta=[5.0], fuera=[6.0]))
        scraper = UTEScraper("user", "password", "account")
        with self.assertLogs(scraper_module.__name__, level="WARNING") as captured:
            result = await scraper._fetch_consumption_data(
                page, "98765", date(2026, 9, 28), date(2026, 9, 28)
            )
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.daily_peak_energy_kwh)
        self.assertIsNone(result.daily_off_peak_energy_kwh)
        self.assertNotIn("2026-09-28", result.daily_energy_kwh)
        self.assertTrue(any("28-09-2026" in line for line in captured.output))
        self.assertNotIn("98765", "\n".join(captured.output))

    async def test_range_mismatch_does_not_claim_the_requested_day(self) -> None:
        page = _page(_tramo("27-09-2026 a 27-09-2026 (DOBLE17)", punta=[9.0], fuera=[1.0]))
        scraper = UTEScraper("user", "password", "account")
        with self.assertLogs(scraper_module.__name__, level="WARNING") as captured:
            result = await scraper._fetch_consumption_data(
                page, "98765", date(2026, 9, 28), date(2026, 9, 28)
            )
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.daily_peak_energy_kwh)
        self.assertIsNone(result.peak_energy_kwh)
        self.assertTrue(captured.output)
        self.assertNotIn("98765", "\n".join(captured.output))

    async def test_month_range_label_is_not_a_single_day(self) -> None:
        page = _page(_tramo("01-09-2026 a 28-09-2026 (DOBLE17)", punta=[9.0], fuera=[1.0]))
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.peak_energy_kwh)

    async def test_info_range_conflict_rejects_the_day(self) -> None:
        page = _page(
            _tramo(
                "28-09-2026 a 28-09-2026 (DOBLE17)",
                punta=[1.0],
                fuera=[1.0],
                info={"inicio": "27-09-2026", "fin": "28-09-2026", "tarifa": "DOBLE17"},
            )
        )
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.peak_energy_kwh)

    async def test_only_one_tariff_does_not_invent_the_daily_total(self) -> None:
        page = _page(_tramo("28-09-2026 a 28-09-2026 (DOBLE17)", fuera=[2.0]))
        result = await UTEScraper("user", "password", "account")._fetch_consumption_data(
            page, "98765", date(2026, 9, 28), date(2026, 9, 28)
        )
        self.assertEqual(result.daily_energy_kwh, {})
        self.assertIsNone(result.daily_peak_energy_kwh)
        self.assertEqual(result.daily_off_peak_energy_kwh, {"2026-09-28": 2.0})
        self.assertIsNone(result.peak_energy_kwh)

    async def test_malformed_numbers_and_lengths_are_refused(self) -> None:
        scraper = UTEScraper("user", "password", "account")
        cases = [
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[-1.0], fuera=[1.0]),
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[float("nan")], fuera=[1.0]),
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[float("inf")], fuera=[1.0]),
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=["1.5"], fuera=[1.0]),
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[True], fuera=[1.0]),
            _tramo("28-09-2026 a 28-09-2026 (DOBLE17)", punta=[1.0, 2.0], fuera=[1.0]),
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(UTEScraperError):
                    await scraper._fetch_consumption_data(
                        _page(payload), "98765", date(2026, 9, 28), date(2026, 9, 28)
                    )


class TestDailyRoundTrip(unittest.IsolatedAsyncioTestCase):
    def _scraper(self) -> tuple[UTEScraper, MagicMock, MagicMock]:
        scraper = UTEScraper("user", "password", "account")
        page = MagicMock()
        context = MagicMock()
        context.close = AsyncMock()
        scraper._authenticated_page = AsyncMock(return_value=(context, page))
        scraper._get_sp_id = AsyncMock(return_value="98765")
        return scraper, page, context

    def _route(self, page: MagicMock, responses: dict[tuple[str, str], dict | str]) -> None:
        async def inner_text() -> str:
            url = page.goto.await_args.args[0]
            for (start, end), payload in responses.items():
                if f"[fechaInicial]={start}" in url and f"[fechaFinal]={end}" in url:
                    return payload if isinstance(payload, str) else json.dumps(payload)
            raise AssertionError(f"unexpected url {url}")

        body = MagicMock()
        body.inner_text = AsyncMock(side_effect=inner_text)
        page.goto = AsyncMock()
        page.locator.return_value = body

    async def test_reuses_session_and_skips_invalid_days_without_duplicates(self) -> None:
        scraper, page, context = self._scraper()
        self._route(
            page,
            {
                ("01-09-2026", "02-09-2026"): _tramo(
                    "01-09-2026 a 02-09-2026 (DOBLE17)", punta=[10.0], fuera=[20.0]
                ),
                ("01-09-2026", "01-09-2026"): _tramo(
                    "01-09-2026 a 01-09-2026 (DOBLE17)", punta=[1.0], fuera=[2.0]
                ),
                ("02-09-2026", "02-09-2026"): _tramo(
                    "02-09-2026 a 02-09-2026 (DOBLE17)", punta=[-3.0], fuera=[1.0]
                ),
                ("31-08-2026", "31-08-2026"): _tramo(
                    "31-08-2026 a 31-08-2026 (DOBLE17)", punta=[0.0], fuera=[4.0]
                ),
            },
        )
        moment = datetime(2026, 9, 3, 12, 0, tzinfo=UY)
        with _freeze(moment), self.assertLogs(scraper_module.__name__, level="WARNING"):
            result = await scraper.get_consumption_data(history_start=date(2026, 8, 31))

        self.assertEqual(result.peak_energy_kwh, 10.0)
        self.assertEqual(result.off_peak_energy_kwh, 20.0)
        self.assertEqual(result.total_energy_kwh, 30.0)
        self.assertEqual(
            result.daily_energy_kwh,
            {"2026-08-31": 4.0, "2026-09-01": 3.0},
        )
        self.assertEqual(
            result.daily_peak_energy_kwh,
            {"2026-08-31": 0.0, "2026-09-01": 1.0},
        )
        self.assertNotIn("2026-09-02", result.daily_energy_kwh)
        self.assertNotIn("2026-09-03", result.daily_energy_kwh)
        urls = _urls(page)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(any("[fechaInicial]=01-09-2026" in url and "[fechaFinal]=02-09-2026" in url for url in urls))
        self.assertTrue(any("[fechaFinal]=31-08-2026" in url and "[fechaInicial]=31-08-2026" in url for url in urls))
        self.assertFalse(any("[fechaInicial]=30-08-2026" in url for url in urls))
        self.assertFalse(any("[fechaFinal]=03-09-2026" in url for url in urls))
        context.close.assert_awaited()

    async def test_multi_month_outage_queries_every_completed_day_once(self) -> None:
        scraper, page, context = self._scraper()

        async def inner_text() -> str:
            url = page.goto.await_args.args[0]
            start = url.split("[fechaInicial]=")[1].split("&")[0]
            end = url.split("[fechaFinal]=")[1].split("&")[0]
            return json.dumps(
                _tramo(f"{start} a {end} (DOBLE17)", punta=[1.0], fuera=[1.0])
            )

        body = MagicMock()
        body.inner_text = AsyncMock(side_effect=inner_text)
        page.goto = AsyncMock()
        page.locator.return_value = body
        with _freeze(datetime(2026, 9, 3, 12, 0, tzinfo=UY)):
            result = await scraper.get_consumption_data(history_start=date(2026, 7, 15))

        expected = []
        day = date(2026, 7, 15)
        while day <= date(2026, 9, 2):
            expected.append(day)
            day += timedelta(days=1)
        urls = _urls(page)
        single_days = []
        for url in urls:
            start = url.split("[fechaInicial]=")[1].split("&")[0]
            end = url.split("[fechaFinal]=")[1].split("&")[0]
            if start == end:
                single_days.append(datetime.strptime(start, "%d-%m-%Y").date())
            else:
                self.assertEqual((start, end), ("01-09-2026", "02-09-2026"))
        self.assertEqual(single_days, expected)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertFalse(any("14-07-2026" in url or "03-09-2026" in url for url in urls))
        self.assertEqual(
            set(result.daily_energy_kwh),
            {item.isoformat() for item in expected},
        )
        self.assertNotIn("2026-09-03", result.daily_energy_kwh)
        cast(AsyncMock, scraper._authenticated_page).assert_awaited_once()
        context.close.assert_awaited_once()

    async def test_without_history_queries_only_the_completed_local_month(self) -> None:
        scraper, page, _context = self._scraper()

        async def inner_text() -> str:
            url = page.goto.await_args.args[0]
            start = url.split("[fechaInicial]=")[1].split("&")[0]
            end = url.split("[fechaFinal]=")[1].split("&")[0]
            return json.dumps(_tramo(f"{start} a {end} (DOBLE17)", punta=[1.25], fuera=[0.75]))

        body = MagicMock()
        body.inner_text = AsyncMock(side_effect=inner_text)
        page.goto = AsyncMock()
        page.locator.return_value = body
        with _freeze(datetime(2026, 9, 3, 12, 0, tzinfo=UY)):
            result = await scraper.get_consumption_data()
        urls = _urls(page)
        self.assertTrue(all("09-2026" in url for url in urls))
        self.assertEqual(result.daily_energy_kwh, {"2026-09-01": 2.0, "2026-09-02": 2.0})
        self.assertNotIn("2026-09-03", result.daily_energy_kwh)


if __name__ == "__main__":
    logging.basicConfig(level="DEBUG")
    unittest.main()
