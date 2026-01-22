import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import requests

sys.path.append("/app")

from ute_pkg.ute_scraper import UTEScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("UTEAddon")

# Supervisor API configuration
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
SUPERVISOR_API = "http://supervisor/core/api"
HEADERS = {
    "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
    "Content-Type": "application/json",
}


def get_config():
    """Read config from /data/options.json"""
    config_path = Path("/data/options.json")
    if not config_path.exists():
        # Fallback for local testing
        return {
            "username": os.environ.get("UTE_USERNAME"),
            "password": os.environ.get("UTE_PASSWORD"),
            "account_id": os.environ.get("UTE_ACCOUNT_ID"),
            "scan_interval": 60,
        }
    with open(config_path, "r") as f:
        return json.load(f)


def update_sensor(entity_id, state, attributes=None, unit=None, icon=None, device_class=None, state_class=None):
    """Update a sensor state via Supervisor API."""
    url = f"{SUPERVISOR_API}/states/sensor.{entity_id}"
    payload = {
        "state": state,
        "attributes": attributes or {},
    }
    if unit:
        payload["attributes"]["unit_of_measurement"] = unit
    if icon:
        payload["attributes"]["icon"] = icon
    if device_class:
        payload["attributes"]["device_class"] = device_class
    if state_class:
        payload["attributes"]["state_class"] = state_class

    # Friendly name attribute
    friendly = entity_id.replace("ute_", "UTE ").replace("_", " ").title()
    payload["attributes"]["friendly_name"] = friendly

    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        response.raise_for_status()
        logger.debug(f"Updated {entity_id}: {state}")
    except Exception as e:
        logger.error(f"Failed to update sensor {entity_id}: {e}")


async def main():
    logger.info("UTE Consumo Add-on started")

    config = get_config()
    username = config.get("username")
    password = config.get("password")
    account_id = config.get("account_id")
    scan_interval = config.get("scan_interval", 60)  # Minutes

    if not username or not password or not account_id:
        logger.error("Username, password, and account_id are required in configuration")
        return

    while True:
        logger.info("Starting scrape cycle...")
        scraper = UTEScraper(username, password, account_id)
        try:
            data = await scraper.get_consumption_data()

            if data:
                # Update sensors
                if data.peak_energy_kwh is not None:
                    update_sensor(
                        "ute_energia_punta",
                        data.peak_energy_kwh,
                        unit="kWh",
                        icon="mdi:flash",
                        device_class="energy",
                        state_class="total_increasing",
                    )

                if data.off_peak_energy_kwh is not None:
                    update_sensor(
                        "ute_energia_fuera_punta",
                        data.off_peak_energy_kwh,
                        unit="kWh",
                        icon="mdi:flash-outline",
                        device_class="energy",
                        state_class="total_increasing",
                    )

                if data.total_energy_kwh is not None:
                    update_sensor(
                        "ute_energia_total",
                        data.total_energy_kwh,
                        unit="kWh",
                        icon="mdi:lightning-bolt",
                        device_class="energy",
                        state_class="total_increasing",
                    )

                if data.efficiency is not None:
                    update_sensor(
                        "ute_eficiencia",
                        data.efficiency,
                        unit="%",
                        icon="mdi:percent",
                    )

                if data.fecha_inicial and data.fecha_final:
                    update_sensor(
                        "ute_periodo",
                        f"{data.fecha_inicial} - {data.fecha_final}",
                        icon="mdi:calendar-range",
                    )

                logger.info(
                    f"Scrape OK: Punta={data.peak_energy_kwh}kWh, "
                    f"FueraPunta={data.off_peak_energy_kwh}kWh, "
                    f"Total={data.total_energy_kwh}kWh"
                )
            else:
                logger.warning("Scrape finished but no data returned.")

        except Exception as e:
            logger.error(f"Error during scrape: {e}")
        finally:
            await scraper.close()

        logger.info(f"Sleeping for {scan_interval} minutes...")
        await asyncio.sleep(scan_interval * 60)


if __name__ == "__main__":
    asyncio.run(main())
