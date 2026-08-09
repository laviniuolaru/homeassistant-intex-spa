"""Read-only values the spa reports."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import DP_TEMP_CURRENT, DP_TIMER
from .entity import IntexSpaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    reported = coordinator.data or {}
    entities: list[SensorEntity] = []
    if DP_TEMP_CURRENT in reported:
        entities.append(IntexSpaTemperature(coordinator))
    if DP_TIMER in reported:
        entities.append(IntexSpaTimeRemaining(coordinator))
    async_add_entities(entities)


class IntexSpaTemperature(IntexSpaEntity, SensorEntity):
    """Water temperature, duplicated out of the water heater so it can be graphed."""

    _attr_translation_key = "water_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "water_temperature")

    @property
    def native_value(self) -> float | None:
        value = self.dp(DP_TEMP_CURRENT)
        return float(value) if isinstance(value, (int, float)) else None


class IntexSpaTimeRemaining(IntexSpaEntity, SensorEntity):
    """Minutes left on the panel timer; zero means no timer is running."""

    _attr_translation_key = "time_remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "time_remaining")

    @property
    def native_value(self) -> int | None:
        value = self.dp(DP_TIMER)
        return int(value) if isinstance(value, (int, float)) else None
