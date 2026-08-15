"""Home Assistant add-on entry point for UTE consumption sensors."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from ute_pkg.ute_scraper import UTEConsumoData, UTEScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("UTEAddon")

SUPERVISOR_API = "http://supervisor/core/api"
STATE_FILE = Path("/data/ute_state.json")
URUGUAY_TZ = timezone(timedelta(hours=-3))


def get_config() -> dict[str, Any]:
    """Read add-on options, with environment variables for local testing."""
    config_file = Path("/data/options.json")
    if config_file.exists():
        with config_file.open(encoding="utf-8") as file:
            return json.load(file)
    return {
        "username": os.environ.get("UTE_USERNAME"),
        "password": os.environ.get("UTE_PASSWORD"),
        "account_id": os.environ.get("UTE_ACCOUNT_ID"),
        "scan_interval": 60,
    }


def load_state() -> dict[str, Any]:
    """Load the small amount of data required for daily consumption."""
    try:
        with STATE_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as err:
        LOGGER.warning("Unable to load saved state: %s", err)
        return {}


def save_state(state: dict[str, Any]) -> None:
    """Atomically persist daily-consumption state."""
    temporary_file = STATE_FILE.with_suffix(".tmp")
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, separators=(",", ":"))
        temporary_file.replace(STATE_FILE)
    except OSError as err:
        LOGGER.error("Unable to save state: %s", err)


def calculate_daily_consumption(
    current: UTEConsumoData, state: dict[str, Any]
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Calculate the current day's use from the monthly cumulative values."""
    today = datetime.now(URUGUAY_TZ).strftime("%Y-%m-%d")
    current_values = {
        "peak": current.peak_energy_kwh,
        "off_peak": current.off_peak_energy_kwh,
        "total": current.total_energy_kwh,
    }
    previous_values = state.get("last_values", {})
    baseline = state.get("daily_baseline")

    if state.get("last_date") and not baseline:
        # Upgrade state written by earlier add-on versions, which retained only
        # the previous cumulative values.
        baseline = previous_values

    if state.get("last_date") and state["last_date"] != today:
        # Keep the final cumulative reading from yesterday as today's baseline.
        # UTE often publishes yesterday's last reading a few hours after
        # midnight, so the daily value must be recalculated on every scrape.
        baseline = previous_values

    if baseline:
        daily = {
            key: _daily_delta(current_values[key], baseline.get(key))
            for key in current_values
        }
    else:
        daily = {"peak": None, "off_peak": None, "total": None}

    new_state = {
        "last_date": today,
        "last_values": current_values,
        "daily_baseline": baseline or current_values,
        "daily_peak": daily["peak"],
        "daily_off_peak": daily["off_peak"],
        "daily_total": daily["total"],
    }
    return daily, new_state


def _daily_delta(current: float | None, previous: float | None) -> float | None:
    """Return a daily delta, handling the monthly counter reset."""
    if current is None or previous is None:
        return None
    delta = round(current - previous, 2)
    return current if delta < 0 else delta


def update_sensor(
    session: requests.Session,
    entity_id: str,
    state: Any,
    **attributes: Any,
) -> None:
    """Publish one sensor state through the Home Assistant Supervisor API."""
    payload = {
        "state": state,
        "attributes": {
            "friendly_name": entity_id.replace("ute_", "UTE ").replace("_", " ").title(),
            **{key: value for key, value in attributes.items() if value is not None},
        },
    }
    try:
        response = session.post(
            f"{SUPERVISOR_API}/states/sensor.{entity_id}", json=payload, timeout=10
        )
        response.raise_for_status()
    except requests.RequestException as err:
        LOGGER.error("Unable to update %s: %s", entity_id, err)


def publish_data(
    session: requests.Session,
    data: UTEConsumoData,
    daily: dict[str, float | None],
) -> None:
    """Publish all UTE sensor values from declarative definitions."""
    measurements = (
        ("ute_energia_punta", data.peak_energy_kwh, "mdi:flash", "energy", "total_increasing"),
        ("ute_energia_fuera_punta", data.off_peak_energy_kwh, "mdi:flash-outline", "energy", "total_increasing"),
        ("ute_energia_total", data.total_energy_kwh, "mdi:lightning-bolt", "energy", "total_increasing"),
        ("ute_eficiencia", data.efficiency, "mdi:percent", None, None),
        ("ute_diario_punta", daily["peak"], "mdi:flash", "energy", "total"),
        ("ute_diario_fuera_punta", daily["off_peak"], "mdi:flash-outline", "energy", "total"),
        ("ute_diario_total", daily["total"], "mdi:lightning-bolt", "energy", "total"),
    )
    for entity_id, value, icon, device_class, state_class in measurements:
        if value is None:
            continue
        update_sensor(
            session,
            entity_id,
            value,
            unit_of_measurement="%" if entity_id == "ute_eficiencia" else "kWh",
            icon=icon,
            device_class=device_class,
            state_class=state_class,
        )

    if data.fecha_inicial and data.fecha_final:
        update_sensor(
            session,
            "ute_periodo",
            f"{data.fecha_inicial} - {data.fecha_final}",
            icon="mdi:calendar-range",
        )


async def main() -> None:
    """Run the add-on until Home Assistant stops it."""
    config = get_config()
    if not all(config.get(key) for key in ("username", "password", "account_id")):
        LOGGER.error("username, password, and account_id are required")
        return

    interval_seconds = max(int(config.get("scan_interval", 60)), 1) * 60
    scraper = UTEScraper(config["username"], config["password"], config["account_id"])
    state = load_state()
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}",
            "Content-Type": "application/json",
        }
    )

    LOGGER.info("UTE Consumo add-on started")
    try:
        while True:
            try:
                data = await scraper.get_consumption_data()
                daily, state = calculate_daily_consumption(data, state)
                save_state(state)
                publish_data(session, data, daily)
                LOGGER.info(
                    "Scrape OK: total=%skWh, daily=%skWh",
                    data.total_energy_kwh,
                    daily["total"],
                )
            except Exception as err:
                LOGGER.error("Scrape failed: %s", err)
            finally:
                # A Chromium process consumes substantially more memory than the
                # add-on itself.  Scrapes are minutes apart, so keep it alive
                # only for the duration of one scrape and release its memory
                # between updates.  UTEScraper starts it again on demand.
                await scraper.close()
            await asyncio.sleep(interval_seconds)
    finally:
        session.close()
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
