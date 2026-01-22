import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
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

# State file for daily calculations
STATE_FILE = Path("/data/ute_state.json")


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


def load_state() -> dict:
    """Load previous state from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    return {}


def save_state(state: dict):
    """Save state to file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def calculate_daily_consumption(current_data, state: dict) -> dict:
    """Calculate daily consumption from cumulative values.
    
    Returns dict with daily values and updated state.
    """
    # Get Uruguay timezone (UTC-3)
    uy_tz = timezone(timedelta(hours=-3))
    today = datetime.now(uy_tz).strftime("%Y-%m-%d")
    
    daily = {
        "peak": None,
        "off_peak": None,
        "total": None,
    }
    
    last_date = state.get("last_date")
    last_values = state.get("last_values", {})
    
    # If it's a new day, calculate delta from yesterday's final values
    if last_date and last_date != today and last_values:
        # New day - calculate delta
        if current_data.peak_energy_kwh is not None and last_values.get("peak") is not None:
            daily["peak"] = round(current_data.peak_energy_kwh - last_values["peak"], 2)
            if daily["peak"] < 0:  # Month reset
                daily["peak"] = current_data.peak_energy_kwh
                
        if current_data.off_peak_energy_kwh is not None and last_values.get("off_peak") is not None:
            daily["off_peak"] = round(current_data.off_peak_energy_kwh - last_values["off_peak"], 2)
            if daily["off_peak"] < 0:  # Month reset
                daily["off_peak"] = current_data.off_peak_energy_kwh
                
        if current_data.total_energy_kwh is not None and last_values.get("total") is not None:
            daily["total"] = round(current_data.total_energy_kwh - last_values["total"], 2)
            if daily["total"] < 0:  # Month reset
                daily["total"] = current_data.total_energy_kwh
        
        logger.info(f"New day detected. Daily consumption: peak={daily['peak']}, off_peak={daily['off_peak']}, total={daily['total']}")
    
    elif last_date == today:
        # Same day - keep existing daily values
        daily["peak"] = state.get("daily_peak")
        daily["off_peak"] = state.get("daily_off_peak")
        daily["total"] = state.get("daily_total")
    
    # Update state with current values
    new_state = {
        "last_date": today,
        "last_values": {
            "peak": current_data.peak_energy_kwh,
            "off_peak": current_data.off_peak_energy_kwh,
            "total": current_data.total_energy_kwh,
        },
        "daily_peak": daily["peak"],
        "daily_off_peak": daily["off_peak"],
        "daily_total": daily["total"],
    }
    
    return {"daily": daily, "state": new_state}


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

    # Load previous state
    state = load_state()
    
    while True:
        logger.info("Starting scrape cycle...")
        scraper = UTEScraper(username, password, account_id)
        try:
            data = await scraper.get_consumption_data()

            if data:
                # Calculate daily consumption
                daily_result = calculate_daily_consumption(data, state)
                daily = daily_result["daily"]
                state = daily_result["state"]
                save_state(state)
                
                # Update cumulative sensors
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

                # Update daily consumption sensors
                if daily["peak"] is not None:
                    update_sensor(
                        "ute_diario_punta",
                        daily["peak"],
                        unit="kWh",
                        icon="mdi:flash",
                        device_class="energy",
                        state_class="total",
                    )

                if daily["off_peak"] is not None:
                    update_sensor(
                        "ute_diario_fuera_punta",
                        daily["off_peak"],
                        unit="kWh",
                        icon="mdi:flash-outline",
                        device_class="energy",
                        state_class="total",
                    )

                if daily["total"] is not None:
                    update_sensor(
                        "ute_diario_total",
                        daily["total"],
                        unit="kWh",
                        icon="mdi:lightning-bolt",
                        device_class="energy",
                        state_class="total",
                    )

                logger.info(
                    f"Scrape OK: Punta={data.peak_energy_kwh}kWh, "
                    f"FueraPunta={data.off_peak_energy_kwh}kWh, "
                    f"Total={data.total_energy_kwh}kWh | "
                    f"Daily: {daily['total']}kWh"
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
