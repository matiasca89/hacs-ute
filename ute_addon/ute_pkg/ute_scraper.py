"""UTE web scraper using Playwright."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,
)

from .const import (
    CHROMIUM_ARGS,
    ELEMENT_TIMEOUT_MS,
    LOGIN_RETRY_DELAYS_SECONDS,
    NAVIGATION_TIMEOUT_MS,
    UTE_LOGIN_URL,
    UTE_SELFSERVICE_URL,
)

_LOGGER = logging.getLogger(__name__)
URUGUAY_TZ = ZoneInfo("America/Montevideo")
_RANGE_LABEL = re.compile(
    r"^(?P<start>\d{2}-\d{2}-\d{4}) a (?P<end>\d{2}-\d{2}-\d{4}) \([^)]+\)$"
)
_ACTIVE_ENERGY = "Energia Activa (kWh)"
_TRANSIENT_NETWORK_ERRORS = (
    "ERR_NETWORK_CHANGED",
    "ERR_CONNECTION_",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_NAME_NOT_RESOLVED",
)


@dataclass
class UTEConsumoData:
    """Data class for UTE consumption data."""

    peak_energy_kwh: float | None = None
    off_peak_energy_kwh: float | None = None
    total_energy_kwh: float | None = None
    efficiency: float | None = None
    fecha_inicial: str | None = None
    fecha_final: str | None = None
    sp_id: str | None = None
    daily_energy_kwh: dict[str, float] = field(default_factory=dict)
    daily_peak_energy_kwh: dict[str, float] | None = None
    daily_off_peak_energy_kwh: dict[str, float] | None = None


class UTEScraperError(Exception):
    """Base exception for UTE scraper."""


class UTEAuthError(UTEScraperError):
    """Authentication error."""


class UTEConnectionError(UTEScraperError):
    """Connection error."""


def _portal_date(value: date) -> str:
    """Format a date the way the UTE chart query expects it."""
    return value.strftime("%d-%m-%Y")


def _completed_period(moment: datetime | None = None) -> tuple[date, date]:
    """Return the previous completed local day and the first day of its month."""
    current = moment or datetime.now(URUGUAY_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=URUGUAY_TZ)
    else:
        current = current.astimezone(URUGUAY_TZ)
    yesterday = current.date() - timedelta(days=1)
    return yesterday.replace(day=1), yesterday


def _inclusive_dates(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _daily_dates(yesterday: date, history_start: date | None) -> list[date]:
    """Completed days from an earlier outage through yesterday, else this month."""
    start = yesterday.replace(day=1)
    if history_start is not None and history_start < start:
        start = history_start
    return _inclusive_dates(start, yesterday)


def _finite_nonnegative(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UTEScraperError("Invalid consumption value")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise UTEScraperError("Invalid consumption value")
    return number


def _series_total(values: list) -> float | None:
    parsed = [_finite_nonnegative(value) for value in values if value is not None]
    if not parsed:
        return None
    return round(sum(parsed), 2)


def _chart_data(payload: dict, chart_key: str) -> tuple[list, list]:
    chart = payload.get("CONSUMO_ACTUAL", {}).get(chart_key, {})
    data = chart.get("data", {}) if isinstance(chart, dict) else {}
    if not isinstance(data, dict):
        raise UTEScraperError("Invalid consumption series")
    labels = data.get("labels") or []
    datasets = data.get("datasets") or []
    if not isinstance(labels, list) or not isinstance(datasets, list):
        raise UTEScraperError("Invalid consumption series")
    if labels and len(labels) != len(set(labels)):
        raise UTEScraperError("Duplicate consumption dates")
    if labels:
        for dataset in datasets:
            points = dataset.get("data", []) if isinstance(dataset, dict) else None
            if not isinstance(points, list) or len(points) != len(labels):
                raise UTEScraperError("Mismatched consumption series length")
    return labels, datasets


def _labeled_values(datasets: list, label: str) -> list | None:
    for dataset in datasets:
        if isinstance(dataset, dict) and dataset.get("label") == label:
            values = dataset.get("data", [])
            if not isinstance(values, list):
                raise UTEScraperError("Invalid consumption series")
            return values
    return None


def _range_label(labels: list) -> tuple[str, str] | None:
    if len(labels) != 1 or not isinstance(labels[0], str):
        return None
    match = _RANGE_LABEL.fullmatch(labels[0].strip())
    if not match:
        return None
    return match.group("start"), match.group("end")


def _info_conflicts(payload: dict, start: str, end: str) -> bool:
    info = payload.get("CONSUMO_ACTUAL", {}).get("infoTramoHorario")
    if not isinstance(info, list) or not info or not isinstance(info[0], dict):
        return bool(info)
    item = info[0]
    if "inicio" in item and item.get("inicio") != start:
        return True
    if "fin" in item and item.get("fin") != end:
        return True
    return False


def _optional_total(values: list | None) -> float | None:
    if values is None:
        return None
    return _series_total(values)


def _monthly_total(
    active_energy: float | None,
    reported_total: float | None,
    peak: float | None,
    off_peak: float | None,
) -> float | None:
    """Prefer named active energy, then a real Total, then both tariff series."""
    if active_energy is not None:
        return active_energy
    if peak is not None and off_peak is not None:
        tariff_sum: float | None = round(peak + off_peak, 2)
    else:
        tariff_sum = None
    if (reported_total is None or reported_total == 0) and tariff_sum is not None and tariff_sum > 0:
        return tariff_sum
    if reported_total is not None:
        return reported_total
    return tariff_sum


def _empty_consumption(
    fecha_inicial: str, fecha_final: str, sp_id: str
) -> UTEConsumoData:
    return UTEConsumoData(
        fecha_inicial=fecha_inicial,
        fecha_final=fecha_final,
        sp_id=sp_id,
    )


class UTEScraper:
    """Scraper for UTE consumption data using Playwright."""

    def __init__(
        self,
        username: str,
        password: str,
        account_id: str,
    ) -> None:
        """Initialize the scraper."""
        self._username = username
        self._password = password
        self._account_id = account_id
        self._browser: Browser | None = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        """Ensure browser is available."""
        if self._browser is None or not self._browser.is_connected():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=CHROMIUM_ARGS,
            )
        return self._browser

    async def close(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _new_context(self, browser: Browser) -> BrowserContext:
        """Create an isolated browser context for an UTE session."""
        return await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

    async def _login(self, page: Page) -> bool:
        """Perform login on UTE page."""
        try:
            _LOGGER.debug("Navigating to UTE login page")
            await page.goto(
                UTE_LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )

            # Fill username
            username_input = page.locator('input[name="Username"]')
            await username_input.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
            await username_input.fill(self._username)

            # Fill password
            password_input = page.locator('input[name="Password"]')
            await password_input.fill(self._password)

            # Submit through the visible login control. Sending Enter to the
            # password field can leave the identity provider waiting forever.
            login_button = page.get_by_role("button", name="Ingresar")
            # UTE sometimes starts a navigation which never reaches Playwright's
            # navigation-complete state. Do not make the click wait for it; wait
            # for the authenticated-session indicator below instead.
            await login_button.click(timeout=ELEMENT_TIMEOUT_MS, no_wait_after=True)

            # The provider redirects after authenticating; waiting for
            # networkidle is unreliable because the resulting page keeps
            # background requests open.
            logout_link = page.get_by_text(re.compile(r"Cerrar sesi.n", re.I))
            await logout_link.first.wait_for(
                state="attached", timeout=ELEMENT_TIMEOUT_MS
            )
            _LOGGER.debug("Login successful")
            return True

        except PlaywrightTimeout as err:
            _LOGGER.error("Timeout during login: %s", err)
            raise UTEConnectionError("Timeout connecting to UTE") from err
        except UTEAuthError:
            raise
        except Exception as err:
            _LOGGER.error("Error during login: %s", err)
            if any(error in str(err) for error in _TRANSIENT_NETWORK_ERRORS):
                raise UTEConnectionError("Temporary network error connecting to UTE") from err
            raise UTEScraperError(f"Login error: {err}") from err

    async def _get_sp_id(self, page: Page) -> str | None:
        """Navigate to account and extract spId."""
        try:
            # Navigate to account page
            account_url = f"{UTE_SELFSERVICE_URL}/account?accountId={self._account_id}"
            await page.goto(
                account_url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )

            # Wait for table
            await page.wait_for_selector(".jtable", timeout=ELEMENT_TIMEOUT_MS)

            # Click on the account row
            row_selector = f'tr[data-record-key="{self._account_id}"]'
            row = page.locator(row_selector)
            await row.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
            await row.click()

            # Wait for the link with curva de carga (use .first as there may be multiple)
            # Use "attached" state since the element may not be visible
            link_selector = 'a.btn.btn-primary.btn-block[href*="cmvisualizarcurvadecarga"]'
            link = page.locator(link_selector).first
            await link.wait_for(state="attached", timeout=ELEMENT_TIMEOUT_MS)

            # Extract spId from href
            href = await link.get_attribute("href")
            if href:
                match = re.search(r"spId=(\d+)", href)
                if match:
                    return match.group(1)

            return None

        except Exception as err:
            _LOGGER.error("Error getting spId: %s", type(err).__name__)
            raise UTEScraperError("Failed to get spId") from err

    async def _fetch_consumption_data(
        self,
        page: Page,
        sp_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> UTEConsumoData:
        """Fetch one chart range. Daily maps are filled only for a proven single day."""
        try:
            default_start, default_end = _completed_period()
            start = start_date or default_start
            end = end_date or default_end
            fecha_inicial = _portal_date(start)
            fecha_final = _portal_date(end)
            data_url = (
                f"{UTE_SELFSERVICE_URL}/cmgraficar?"
                f"graficas[0][name]=CONSUMO_ACTUAL&"
                f"graficas[0][parms][psId]={sp_id}&"
                f"graficas[0][parms][fechaInicial]={fecha_inicial}&"
                f"graficas[0][parms][fechaFinal]={fecha_final}"
            )
            _LOGGER.debug(
                "Fetching UTE consumption range %s to %s", fecha_inicial, fecha_final
            )
            await page.goto(
                data_url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            json_data = json.loads(await page.locator("body").inner_text())
            labels, datasets = _chart_data(json_data, "consumoActualTramoHorario")
            _, active_datasets = _chart_data(json_data, "consumoActual")
            peak = _optional_total(_labeled_values(datasets, "Punta"))
            off_peak = _optional_total(_labeled_values(datasets, "Fuera de Punta"))
            reported_total = _optional_total(_labeled_values(datasets, "Total"))
            active_energy = _optional_total(
                _labeled_values(active_datasets, _ACTIVE_ENERGY)
            )
            observed = _range_label(labels)
            conflicts = bool(observed) and _info_conflicts(
                json_data, observed[0], observed[1]
            )
            matches = observed == (fecha_inicial, fecha_final) and not conflicts
            single_day = start == end
            if observed is not None and not matches:
                _LOGGER.warning(
                    "UTE response range did not match requested %s to %s",
                    fecha_inicial,
                    fecha_final,
                )
                return _empty_consumption(fecha_inicial, fecha_final, sp_id)
            if single_day and not matches:
                _LOGGER.warning(
                    "UTE daily response has no authoritative range for %s",
                    fecha_inicial,
                )
            total = _monthly_total(active_energy, reported_total, peak, off_peak)
            efficiency = None
            if peak is not None and off_peak is not None and (peak + off_peak) > 0:
                efficiency = round((off_peak * 100) / (peak + off_peak), 2)
            daily_energy: dict[str, float] = {}
            daily_peak = None
            daily_off = None
            if single_day and matches:
                iso_day = start.isoformat()
                if peak is not None:
                    daily_peak = {iso_day: peak}
                if off_peak is not None:
                    daily_off = {iso_day: off_peak}
                if active_energy is not None:
                    daily_energy = {iso_day: active_energy}
                elif peak is not None and off_peak is not None:
                    daily_energy = {iso_day: round(peak + off_peak, 2)}
            return UTEConsumoData(
                peak_energy_kwh=peak,
                off_peak_energy_kwh=off_peak,
                total_energy_kwh=total,
                efficiency=efficiency,
                fecha_inicial=fecha_inicial,
                fecha_final=fecha_final,
                sp_id=sp_id,
                daily_energy_kwh=daily_energy,
                daily_peak_energy_kwh=daily_peak,
                daily_off_peak_energy_kwh=daily_off,
            )
        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse JSON response")
            raise UTEScraperError("Invalid JSON response from UTE") from err
        except UTEScraperError:
            raise
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", type(err).__name__)
            raise UTEScraperError("Failed to fetch data") from err

    async def get_consumption_data(
        self, history_start: date | None = None
    ) -> UTEConsumoData:
        """Get the completed local month and one proven point per completed day."""
        context, page = await self._authenticated_page()
        try:
            sp_id = await self._get_sp_id(page)
            if not sp_id:
                raise UTEScraperError("Could not extract spId from account")
            month_start, yesterday = _completed_period()
            monthly = await self._fetch_consumption_data(
                page, sp_id, month_start, yesterday
            )
            totals: dict[str, float] = {}
            peaks: dict[str, float] = {}
            off_peaks: dict[str, float] = {}
            for day in _daily_dates(yesterday, history_start):
                try:
                    point = await self._fetch_consumption_data(page, sp_id, day, day)
                except UTEScraperError:
                    _LOGGER.warning(
                        "Skipping UTE day %s after an invalid response",
                        day.isoformat(),
                    )
                    continue
                iso_day = day.isoformat()
                if iso_day in point.daily_energy_kwh and iso_day not in totals:
                    totals[iso_day] = point.daily_energy_kwh[iso_day]
                if point.daily_peak_energy_kwh and iso_day not in peaks:
                    peak_value = point.daily_peak_energy_kwh.get(iso_day)
                    if peak_value is not None:
                        peaks[iso_day] = peak_value
                if point.daily_off_peak_energy_kwh and iso_day not in off_peaks:
                    off_value = point.daily_off_peak_energy_kwh.get(iso_day)
                    if off_value is not None:
                        off_peaks[iso_day] = off_value
            monthly.daily_energy_kwh = totals
            monthly.daily_peak_energy_kwh = peaks or None
            monthly.daily_off_peak_energy_kwh = off_peaks or None
            return monthly
        finally:
            await context.close()

    async def _authenticated_page(self) -> tuple[BrowserContext, Page]:
        """Create a fresh authenticated UTE session, retrying connection failures."""
        browser = await self._ensure_browser()

        for attempt in range(len(LOGIN_RETRY_DELAYS_SECONDS) + 1):
            context = await self._new_context(browser)
            try:
                page = await context.new_page()
                await self._login(page)
                return context, page
            except UTEConnectionError:
                await context.close()
                if attempt == len(LOGIN_RETRY_DELAYS_SECONDS):
                    raise
                delay = LOGIN_RETRY_DELAYS_SECONDS[attempt]
                _LOGGER.warning(
                    "Connection error, retrying in %s seconds (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    len(LOGIN_RETRY_DELAYS_SECONDS) + 1,
                )
                await asyncio.sleep(delay)
            except Exception:
                await context.close()
                raise

        raise UTEConnectionError("Unable to authenticate with UTE")

    async def validate_credentials(self) -> bool:
        """Validate credentials without fetching all data."""
        context: BrowserContext | None = None
        try:
            context, _ = await self._authenticated_page()
            return True
        except UTEAuthError:
            return False
        finally:
            if context:
                await context.close()
