"""UTE web scraper using Playwright."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeout,
)

from .const import UTE_LOGIN_URL, UTE_SELFSERVICE_URL

_LOGGER = logging.getLogger(__name__)


@dataclass
class UTEConsumoData:
    """Data class for UTE consumption data."""

    peak_energy_kwh: float | None = None
    off_peak_energy_kwh: float | None = None
    total_energy_kwh: float | None = None
    efficiency: float | None = None
    fecha_inicial: str | None = None
    fecha_final: str | None = None
    raw_data: dict[str, Any] | None = None


class UTEScraperError(Exception):
    """Base exception for UTE scraper."""


class UTEAuthError(UTEScraperError):
    """Authentication error."""


class UTEConnectionError(UTEScraperError):
    """Connection error."""


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
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
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

    async def _login(self, page: Page) -> bool:
        """Perform login on UTE page."""
        try:
            _LOGGER.debug("Navigating to UTE login page")
            await page.goto(UTE_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

            # Fill username
            username_input = page.locator('input[name="Username"]')
            await username_input.wait_for(state="visible", timeout=30000)
            await username_input.fill(self._username)

            # Fill password
            password_input = page.locator('input[name="Password"]')
            await password_input.fill(self._password)

            # Submit form
            await password_input.press("Enter")

            # Wait for login to complete
            await page.wait_for_load_state("networkidle", timeout=60000)

            # Check if login was successful
            content = await page.content()
            if "Cerrar sesión" in content or "cerrar sesión" in content.lower():
                _LOGGER.debug("Login successful")
                return True

            _LOGGER.error("Login failed - 'Cerrar sesión' not found in page")
            raise UTEAuthError("Login failed")

        except PlaywrightTimeout as err:
            _LOGGER.error("Timeout during login: %s", err)
            raise UTEConnectionError("Timeout connecting to UTE") from err
        except UTEAuthError:
            raise
        except Exception as err:
            _LOGGER.error("Error during login: %s", err)
            raise UTEScraperError(f"Login error: {err}") from err

    async def _get_sp_id(self, page: Page) -> str | None:
        """Navigate to account and extract spId."""
        try:
            _LOGGER.debug("Navigating to account %s", self._account_id)

            account_url = (
                f"{UTE_SELFSERVICE_URL}/account"
                f"?accountId={self._account_id}"
            )

            # Wait for network to be idle after navigation
            await page.goto(account_url, wait_until="networkidle", timeout=60000)

            _LOGGER.debug("Waiting for supplies table...")

            # Wait for the supplies table to appear
            await page.wait_for_selector("#tablaSuministros", timeout=30000)

            _LOGGER.debug("Extracting spId...")

            # Find any link containing spId
            links = page.locator('a[href*="cmvisualizarcurvadecarga"][href*="spId="]')
            count = await links.count()

            if count == 0:
                return None

            for i in range(count):
                href = await links.nth(i).get_attribute("href")
                if href:
                    match = re.search(r"spId=(\d+)", href)
                    if match:
                        return match.group(1)

            return None

        except Exception as err:
            _LOGGER.error("Error getting spId: %s", err)
            raise UTEScraperError(f"Failed to get spId: {err}") from err

    async def _fetch_consumption_data(
        self, page: Page, sp_id: str
    ) -> UTEConsumoData:
        """Fetch consumption data from UTE API."""
        try:
            # Calculate date range (month of "yesterday" to yesterday)
            # UTE data is day-behind; on the 1st this avoids fecha_inicial > fecha_final.
            end_date = datetime.now(timezone.utc) - timedelta(days=1)
            start_date = end_date.replace(day=1)
            fecha_inicial = start_date.strftime("%d-%m-%Y")
            fecha_final = end_date.strftime("%d-%m-%Y")

            # Build API URL
            data_url = (
                f"{UTE_SELFSERVICE_URL}/cmgraficar?"
                f"graficas[0][name]=CONSUMO_ACTUAL&"
                f"graficas[0][parms][psId]={sp_id}&"
                f"graficas[0][parms][fechaInicial]={fecha_inicial}&"
                f"graficas[0][parms][fechaFinal]={fecha_final}"
            )

            _LOGGER.debug("Fetching data from: %s", data_url)

            # Navigate to JSON endpoint
            await page.goto(data_url, wait_until="domcontentloaded", timeout=60000)

            # Extract JSON from page
            body = page.locator("body")
            json_text = await body.inner_text()

            # Parse JSON
            json_data = json.loads(json_text)

            # Process consumption data
            punta_sum = 0.0
            fuera_de_punta_sum = 0.0
            total_sum = 0.0

            consumo_data = json_data.get("CONSUMO_ACTUAL", {})
            tramo_horario = consumo_data.get("consumoActualTramoHorario", {})
            datasets = tramo_horario.get("data", {}).get("datasets", [])

            for dataset in datasets:
                label = dataset.get("label", "")
                values = dataset.get("data", [])
                valid_values = [v for v in values if v is not None]
                total = sum(valid_values)

                if label == "Punta":
                    punta_sum = total
                elif label == "Fuera de Punta":
                    fuera_de_punta_sum = total
                elif label == "Total":
                    total_sum = total

            # Calculate total from peak + off-peak (API's Total field is often empty)
            calculated_total = punta_sum + fuera_de_punta_sum
            if total_sum == 0 and calculated_total > 0:
                total_sum = calculated_total

            # Calculate efficiency
            efficiency = None
            if punta_sum + fuera_de_punta_sum > 0:
                efficiency = (fuera_de_punta_sum * 100) / (punta_sum + fuera_de_punta_sum)

            return UTEConsumoData(
                peak_energy_kwh=round(punta_sum, 2),
                off_peak_energy_kwh=round(fuera_de_punta_sum, 2),
                total_energy_kwh=round(total_sum, 2),
                efficiency=round(efficiency, 2) if efficiency else None,
                fecha_inicial=fecha_inicial,
                fecha_final=fecha_final,
                raw_data={
                    "json_response": json_data,
                    "sp_id": sp_id,
                },
            )

        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse JSON response: %s", err)
            raise UTEScraperError("Invalid JSON response from UTE") from err
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UTEScraperError(f"Failed to fetch data: {err}") from err

    async def get_consumption_data(self) -> UTEConsumoData:
        """Get consumption data from UTE."""
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        try:
            page = await context.new_page()

            # Login with retries
            for attempt in range(3):
                try:
                    await self._login(page)
                    break
                except UTEConnectionError:
                    if attempt < 2:
                        _LOGGER.warning(
                            "Connection error, retrying in 30 seconds (attempt %d/3)",
                            attempt + 1,
                        )
                        await asyncio.sleep(30)
                        continue
                    raise

            # Get spId
            sp_id = await self._get_sp_id(page)
            if not sp_id:
                raise UTEScraperError("Could not extract spId from account")

            # Fetch consumption data
            data = await self._fetch_consumption_data(page, sp_id)

            return data

        finally:
            await context.close()

    async def validate_credentials(self) -> bool:
        """Validate credentials without fetching all data."""
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        try:
            page = await context.new_page()
            for attempt in range(3):
                try:
                    await self._login(page)
                    return True
                except UTEConnectionError:
                    if attempt < 2:
                        await asyncio.sleep(30)
                        continue
                    raise
            return False
        except UTEAuthError:
            return False
        finally:
            await context.close()
