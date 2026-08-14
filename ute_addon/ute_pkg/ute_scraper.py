"""UTE web scraper using Playwright."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
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
            await page.goto(
                data_url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )

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
                sp_id=sp_id,
            )

        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse JSON response: %s", err)
            raise UTEScraperError("Invalid JSON response from UTE") from err
        except Exception as err:
            _LOGGER.error("Error fetching consumption data: %s", err)
            raise UTEScraperError(f"Failed to fetch data: {err}") from err

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

    async def get_consumption_data(self) -> UTEConsumoData:
        """Get consumption data from UTE."""
        context, page = await self._authenticated_page()
        try:
            sp_id = await self._get_sp_id(page)
            if not sp_id:
                raise UTEScraperError("Could not extract spId from account")
            return await self._fetch_consumption_data(page, sp_id)
        finally:
            await context.close()

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
