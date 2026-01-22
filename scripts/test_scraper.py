#!/usr/bin/env python3
"""Test script for UTE scraper - standalone version."""
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeout,
)

# Constants
UTE_LOGIN_URL = "https://identityserver.ute.com.uy/Account/Login"
UTE_SELFSERVICE_URL = "https://autoservicio.ute.com.uy/SelfService/SSvcController"


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

    def __init__(self, username: str, password: str, account_id: str) -> None:
        self._username = username
        self._password = password
        self._account_id = account_id
        self._browser: Browser | None = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is None or not self._browser.is_connected():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
        return self._browser

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _login(self, page: Page) -> bool:
        try:
            print("  → Navigating to login page...")
            await page.goto(UTE_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

            print("  → Filling credentials...")
            username_input = page.locator('input[name="Username"]')
            await username_input.wait_for(state="visible", timeout=30000)
            await username_input.fill(self._username)

            password_input = page.locator('input[name="Password"]')
            await password_input.fill(self._password)

            print("  → Submitting form...")
            await password_input.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=60000)

            content = await page.content()
            if "Cerrar sesión" in content or "cerrar sesión" in content.lower():
                return True

            raise UTEAuthError("Login failed - 'Cerrar sesión' not found")

        except PlaywrightTimeout as err:
            raise UTEConnectionError(f"Timeout: {err}") from err
        except UTEAuthError:
            raise
        except Exception as err:
            raise UTEScraperError(f"Login error: {err}") from err

    async def _get_sp_id(self, page: Page) -> str | None:
        try:
            print(f"  → Navigating to account {self._account_id}...")
            account_url = f"{UTE_SELFSERVICE_URL}/account?accountId={self._account_id}"
            await page.goto(account_url, wait_until="domcontentloaded", timeout=60000)

            await page.wait_for_selector(".jtable", timeout=30000)

            row = page.locator(f'tr[data-record-key="{self._account_id}"]')
            await row.wait_for(state="visible", timeout=30000)
            await row.click()

            print("  → Extracting spId...")
            # Wait for element to exist (not necessarily visible)
            link = page.locator('a.btn.btn-primary.btn-block[href*="cmvisualizarcurvadecarga"]').first
            await link.wait_for(state="attached", timeout=30000)

            href = await link.get_attribute("href")
            if href:
                match = re.search(r"spId=(\d+)", href)
                if match:
                    return match.group(1)
            return None

        except Exception as err:
            raise UTEScraperError(f"Failed to get spId: {err}") from err

    async def _fetch_consumption_data(self, page: Page, sp_id: str) -> UTEConsumoData:
        try:
            today = datetime.now(timezone.utc)
            fecha_inicial = today.replace(day=1).strftime("%d-%m-%Y")
            fecha_final = (today - timedelta(days=1)).strftime("%d-%m-%Y")

            data_url = (
                f"{UTE_SELFSERVICE_URL}/cmgraficar?"
                f"graficas[0][name]=CONSUMO_ACTUAL&"
                f"graficas[0][parms][psId]={sp_id}&"
                f"graficas[0][parms][fechaInicial]={fecha_inicial}&"
                f"graficas[0][parms][fechaFinal]={fecha_final}"
            )

            print(f"  → Fetching data for period {fecha_inicial} → {fecha_final}...")
            await page.goto(data_url, wait_until="domcontentloaded", timeout=60000)

            body = page.locator("body")
            json_text = await body.inner_text()
            json_data = json.loads(json_text)

            punta_sum = 0.0
            fuera_de_punta_sum = 0.0
            total_sum = 0.0

            datasets = json_data.get("CONSUMO_ACTUAL", {}).get("consumoActualTramoHorario", {}).get("data", {}).get("datasets", [])

            for dataset in datasets:
                label = dataset.get("label", "")
                values = [v for v in dataset.get("data", []) if v is not None]
                total = sum(values)

                if label == "Punta":
                    punta_sum = total
                elif label == "Fuera de Punta":
                    fuera_de_punta_sum = total
                elif label == "Total":
                    total_sum = total

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
                raw_data={"json_response": json_data, "sp_id": sp_id},
            )

        except json.JSONDecodeError as err:
            raise UTEScraperError("Invalid JSON response") from err
        except Exception as err:
            raise UTEScraperError(f"Failed to fetch data: {err}") from err

    async def get_consumption_data(self) -> UTEConsumoData:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )

        try:
            page = await context.new_page()
            await self._login(page)
            sp_id = await self._get_sp_id(page)
            if not sp_id:
                raise UTEScraperError("Could not extract spId")
            return await self._fetch_consumption_data(page, sp_id)
        finally:
            await context.close()


async def main():
    load_dotenv(Path(__file__).parent.parent / ".env")

    username = os.getenv("UTE_USERNAME")
    password = os.getenv("UTE_PASSWORD")
    account_id = os.getenv("UTE_ACCOUNT_ID")

    if not all([username, password, account_id]):
        print("❌ Error: Missing credentials in .env")
        sys.exit(1)

    print(f"🔌 Testing UTE scraper for account: {account_id}")
    print("-" * 50)

    scraper = UTEScraper(username=username, password=password, account_id=account_id)

    try:
        print("🔐 Logging in...")
        data = await scraper.get_consumption_data()

        print("\n" + "=" * 50)
        print("📈 RESULTADOS")
        print("=" * 50)
        print(f"⚡ Energía Punta:         {data.peak_energy_kwh} kWh")
        print(f"🌙 Energía Fuera Punta:   {data.off_peak_energy_kwh} kWh")
        print(f"💡 Energía Total:         {data.total_energy_kwh} kWh")
        print(f"📊 Eficiencia:            {data.efficiency}%")
        print(f"📅 Período:               {data.fecha_inicial} → {data.fecha_final}")
        print(f"🔧 SP ID:                 {data.raw_data.get('sp_id')}")
        print("\n✅ Test completado!")

    except UTEScraperError as err:
        print(f"\n❌ Error: {err}")
        sys.exit(1)
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
