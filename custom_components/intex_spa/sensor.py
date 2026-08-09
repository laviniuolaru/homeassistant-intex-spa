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
from .const import DP_HEAT_STATE, DP_TEMP_CURRENT, DP_TIMER, HEAT_STATES
from .entity import IntexSpaEntity

# The socket thread already serialises the wire; this bounds how much can pile up.
PARALLEL_UPDATES = 0


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
    if DP_HEAT_STATE in reported:
        entities.append(IntexSpaHeatState(coordinator))
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


class IntexSpaHeatState(IntexSpaEntity, SensorEntity):
    """The heater's own three-state view, which the binary sensor has to flatten.

    "warm" - enabled but already at target - is not the same as "off", and collapsing
    both to a plain false loses exactly the distinction that makes this data point
    worth reading. Kept next to the binary sensor rather than replacing it: a two-state
    history graph is what you want to lay over an electricity meter.
    """

    _attr_translation_key = "heat_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEAT_STATES
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "heat_state")

    @property
    def native_value(self) -> str | None:
        value = self.dp(DP_HEAT_STATE)
        # An unlisted value would make Home Assistant log an error on every update, so
        # an unfamiliar model reads as unknown instead.
        return str(value) if value in HEAT_STATES else None
