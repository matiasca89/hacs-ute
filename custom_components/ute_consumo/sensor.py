"""Sensor platform for UTE Consumo integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UTEConsumoCoordinator
from .ute_scraper import UTEConsumoData


@dataclass(frozen=True, kw_only=True)
class UTESensorEntityDescription(SensorEntityDescription):
    """Describes a UTE sensor entity."""

    value_fn: Callable[[UTEConsumoData], Any]


SENSORS: tuple[UTESensorEntityDescription, ...] = (
    UTESensorEntityDescription(
        key="peak_energy",
        translation_key="peak_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:flash",
        value_fn=lambda data: data.peak_energy_kwh,
    ),
    UTESensorEntityDescription(
        key="off_peak_energy",
        translation_key="off_peak_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:flash-outline",
        value_fn=lambda data: data.off_peak_energy_kwh,
    ),
    UTESensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
        value_fn=lambda data: data.total_energy_kwh,
    ),
    UTESensorEntityDescription(
        key="efficiency",
        translation_key="efficiency",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda data: data.efficiency,
    ),
    UTESensorEntityDescription(
        key="billing_period",
        translation_key="billing_period",
        icon="mdi:calendar-range",
        value_fn=lambda data: (
            f"{data.fecha_inicial} - {data.fecha_final}"
            if data.fecha_inicial and data.fecha_final
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UTE Consumo sensors based on a config entry."""
    coordinator: UTEConsumoCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        UTESensor(coordinator, description, entry) for description in SENSORS
    )


class UTESensor(CoordinatorEntity[UTEConsumoCoordinator], SensorEntity):
    """Representation of a UTE Consumo sensor."""

    entity_description: UTESensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UTEConsumoCoordinator,
        description: UTESensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "UTE Energía",
            "manufacturer": "UTE",
            "model": "Autoservicio UTE",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.coordinator.data is None:
            return None

        # Only add raw data for the main sensor (total_energy)
        if self.entity_description.key == "total_energy":
            attrs = {
                "fecha_inicial": self.coordinator.data.fecha_inicial,
                "fecha_final": self.coordinator.data.fecha_final,
            }
            if self.coordinator.data.raw_data:
                attrs["sp_id"] = self.coordinator.data.raw_data.get("sp_id")
            return attrs

        return None
