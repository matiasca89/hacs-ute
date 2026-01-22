"""Data coordinator for UTE Consumo integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_ACCOUNT_ID, DEFAULT_SCAN_INTERVAL, DOMAIN
from .ute_scraper import (
    UTEAuthError,
    UTEConnectionError,
    UTEConsumoData,
    UTEScraper,
    UTEScraperError,
)

_LOGGER = logging.getLogger(__name__)


class UTEConsumoCoordinator(DataUpdateCoordinator[UTEConsumoData]):
    """Coordinator for UTE consumption data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.scraper = UTEScraper(
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            account_id=entry.data[CONF_ACCOUNT_ID],
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> UTEConsumoData:
        """Fetch data from UTE."""
        try:
            _LOGGER.debug("Fetching UTE consumption data")
            data = await self.scraper.get_consumption_data()
            _LOGGER.debug(
                "Fetched data: peak=%s kWh, off_peak=%s kWh, total=%s kWh",
                data.peak_energy_kwh,
                data.off_peak_energy_kwh,
                data.total_energy_kwh,
            )
            return data
        except UTEAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except UTEConnectionError as err:
            _LOGGER.error("Connection error: %s", err)
            raise UpdateFailed(f"Connection failed: {err}") from err
        except UTEScraperError as err:
            _LOGGER.error("Scraper error: %s", err)
            raise UpdateFailed(f"Failed to fetch data: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching UTE data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and close the scraper."""
        await self.scraper.close()
