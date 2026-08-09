"""Water heater entity for the spa's heating element."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_ELECTRIC,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import DP_HEATER, DP_TEMP_CURRENT, DP_TEMP_SET, MAX_TEMP_F, MIN_TEMP_F
from .entity import IntexSpaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([IntexSpaWaterHeater(entry.runtime_data)])


class IntexSpaWaterHeater(IntexSpaEntity, WaterHeaterEntity):
    """Target temperature and on/off for the heater.

    Temperatures are reported in Fahrenheit because that is the unit the spa transports
    them in, whatever the panel displays. Home Assistant converts for the user, which
    avoids a double rounding that would make the setpoint drift by a degree.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_operation_list = [STATE_ELECTRIC, STATE_OFF]
    _attr_min_temp = MIN_TEMP_F
    _attr_max_temp = MAX_TEMP_F
    _attr_precision = 1.0
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "water_heater")

    @property
    def current_temperature(self) -> float | None:
        value = self.dp(DP_TEMP_CURRENT)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        value = self.dp(DP_TEMP_SET)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def current_operation(self) -> str:
        return STATE_ELECTRIC if self.dp(DP_HEATER) else STATE_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        clamped = int(round(min(max(float(temperature), MIN_TEMP_F), MAX_TEMP_F)))
        await self.coordinator.async_set_dp(DP_TEMP_SET, clamped)

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, operation_mode != STATE_OFF)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, False)
