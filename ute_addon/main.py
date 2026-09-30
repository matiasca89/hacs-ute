"""Home Assistant add-on entry point for UTE consumption sensors."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from ute_pkg.energy import history_start, prepare_state, sync_statistics
from ute_pkg.ha_statistics import statistics_client
from ute_pkg.ute_scraper import UTEConsumoData, UTEScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("UTEAddon")

SUPERVISOR_API = "http://supervisor/core/api"
STATE_FILE = Path("/data/ute_state.json")


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
    """Load the dated ledger; never silently reset a corrupted history."""
    try:
        with STATE_FILE.open(encoding="utf-8") as file:
            state = json.load(file)
            if not isinstance(state, dict):
                raise ValueError("Saved UTE state must be an object")
            return state
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, ValueError) as err:
        raise RuntimeError(
            "Unable to load UTE ledger; restore the add-on backup before importing statistics"
        ) from err


def save_state(state: dict[str, Any]) -> None:
    """Atomically persist daily-consumption state."""
    temporary_file = STATE_FILE.with_suffix(".tmp")
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, separators=(",", ":"), allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temporary_file.replace(STATE_FILE)
    except OSError as err:
        raise RuntimeError(
            "Unable to persist UTE ledger; statistics were not imported"
        ) from err


def calculate_daily_consumption(
    current: UTEConsumoData, state: dict[str, Any], account_id: str = "legacy"
) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Use dated UTE readings, never differences of mutable monthly totals."""
    return prepare_state(current, state, account_id)


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
            "friendly_name": entity_id.replace("ute_", "UTE ")
            .replace("_", " ")
            .title(),
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
    daily_date: str | None = None,
    statistic_id: str | None = None,
) -> None:
    """Publish all UTE sensor values from declarative definitions."""
    measurements = (
        ("ute_energia_punta", data.peak_energy_kwh, "mdi:flash", "energy", None),
        (
            "ute_energia_fuera_punta",
            data.off_peak_energy_kwh,
            "mdi:flash-outline",
            "energy",
            None,
        ),
        (
            "ute_energia_total",
            data.total_energy_kwh,
            "mdi:lightning-bolt",
            "energy",
            None,
        ),
        ("ute_eficiencia", data.efficiency, "mdi:percent", None, None),
        ("ute_diario_punta", daily["peak"], "mdi:flash", "energy", None),
        (
            "ute_diario_fuera_punta",
            daily["off_peak"],
            "mdi:flash-outline",
            "energy",
            None,
        ),
        ("ute_diario_total", daily["total"], "mdi:lightning-bolt", "energy", None),
    )
    for entity_id, value, icon, device_class, state_class in measurements:
        update_sensor(
            session,
            entity_id,
            value if value is not None else "unavailable",
            fecha_consumo=daily_date if entity_id.startswith("ute_diario_") else None,
            statistic_id=statistic_id if entity_id == "ute_energia_total" else None,
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
                data = await scraper.get_consumption_data(
                    history_start=history_start(state, config["account_id"])
                )
                daily, state = calculate_daily_consumption(
                    data, state, config["account_id"]
                )
                # Persist before importing: a failed disk write must not strand recorder history.
                save_state(state)
                publish_data(
                    session, data, daily, state["daily_date"], state["statistic_id"]
                )
                if config.get("import_statistics", True):
                    try:
                        async with statistics_client(
                            os.environ.get("SUPERVISOR_TOKEN", "")
                        ) as client:
                            status = await sync_statistics(client.call, state)
                        if (
                            status.get("status") == "verified"
                            and not status.get("pending_days")
                        ):
                            LOGGER.info("Energy statistics synchronized and verified")
                        elif status.get("status") == "pending" and status.get(
                            "imported_days"
                        ):
                            LOGGER.info(
                                "Energy statistics prefix verified; %s days pending from %s",
                                status.get("pending_days"),
                                status.get("first_missing_date"),
                            )
                        elif status.get("status") == "waiting":
                            LOGGER.info(
                                "Energy statistics waiting for confirmed UTE days"
                            )
                        elif status.get("status") == "waiting_for_gap":
                            LOGGER.info(
                                "Energy statistics paused pending missing date %s; %s recorder rows preserved",
                                status.get("first_missing_date"),
                                status.get("preserved_days"),
                            )
                        else:
                            LOGGER.error(
                                "Energy synchronization incomplete: %s", status
                            )
                    except Exception as err:
                        LOGGER.error(
                            "Energy synchronization failed (%s): %s",
                            type(err).__name__,
                            err,
                        )
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
