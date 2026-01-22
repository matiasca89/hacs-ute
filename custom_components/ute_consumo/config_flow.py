"""Config flow for UTE Consumo integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import CONF_ACCOUNT_ID, DOMAIN
from .ute_scraper import (
    UTEAuthError,
    UTEConnectionError,
    UTEScraper,
    UTEScraperError,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ACCOUNT_ID): str,
    }
)


class UTEConsumoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UTE Consumo."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if already configured with same account
            unique_id = f"{user_input[CONF_USERNAME]}_{user_input[CONF_ACCOUNT_ID]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            # Validate credentials
            scraper = UTEScraper(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                account_id=user_input[CONF_ACCOUNT_ID],
            )

            try:
                valid = await scraper.validate_credentials()
                if not valid:
                    errors["base"] = "invalid_auth"
            except UTEAuthError:
                errors["base"] = "invalid_auth"
            except UTEConnectionError:
                errors["base"] = "cannot_connect"
            except UTEScraperError:
                errors["base"] = "unknown"
            except Exception:
                _LOGGER.exception("Unexpected exception during config flow")
                errors["base"] = "unknown"
            finally:
                await scraper.close()

            if not errors:
                return self.async_create_entry(
                    title=f"UTE ({user_input[CONF_ACCOUNT_ID]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
