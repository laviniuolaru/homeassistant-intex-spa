"""Water heater entity for the spa's heating element."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    STATE_ELECTRIC,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import DOMAIN, DP_HEATER, DP_TEMP_CURRENT, DP_TEMP_SET
from .entity import IntexSpaEntity, add_as_they_appear

# The socket thread already serialises the wire; this bounds how much can pile up.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data

    def build(dps, seen):
        # Without these the entity would assert "off" for a heater it cannot see, and
        # write a data point the spa does not have.
        if DP_HEATER in dps and DP_TEMP_SET in dps and "made" not in seen:
            seen.add("made")
            return [IntexSpaWaterHeater(coordinator)]
        return []

    add_as_they_appear(coordinator, async_add_entities, build)


class IntexSpaWaterHeater(IntexSpaEntity, WaterHeaterEntity):
    """Target temperature and on/off for the heater.

    Temperatures are reported in whichever unit the spa itself transports, detected from
    the target it reports. Home Assistant converts for the user, which avoids a double
    rounding that would make the setpoint drift by a degree.
    """

    _attr_name = None
    _attr_operation_list = [STATE_ELECTRIC, STATE_OFF]
    _attr_target_temperature_step = 1.0     # the spa steps in whole degrees, either unit
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "water_heater")

    @property
    def temperature_unit(self) -> str:
        return self.coordinator.temperature_unit

    @property
    def min_temp(self) -> float:
        return self.coordinator.temperature_range[0]

    @property
    def max_temp(self) -> float:
        return self.coordinator.temperature_range[1]

    @property
    def current_temperature(self) -> float | None:
        value = self.dp(DP_TEMP_CURRENT)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        value = self.dp(DP_TEMP_SET)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def current_operation(self) -> str | None:
        heating = self.dp(DP_HEATER)
        if heating is None:
            return None
        return STATE_ELECTRIC if heating else STATE_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        wanted = float(temperature)
        low, high = self.coordinator.temperature_range
        if not low <= wanted <= high:
            # Silently clamping would leave an automation believing it got what it asked
            # for. The service call should fail instead.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="temperature_out_of_range",
                translation_placeholders={"min": str(low), "max": str(high)},
            )
        await self.coordinator.async_set_dp(DP_TEMP_SET, int(round(wanted)))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, operation_mode != STATE_OFF)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, False)
