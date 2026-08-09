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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import DOMAIN, DP_HEATER, DP_TEMP_CURRENT, DP_TEMP_SET, MAX_TEMP_F, MIN_TEMP_F
from .entity import IntexSpaEntity

# The socket thread already serialises the wire; this bounds how much can pile up.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    reported = coordinator.data or {}
    # Same gating as the other platforms: without these the entity would assert "off"
    # for a heater it cannot see, and write a data point the spa does not have.
    if DP_HEATER in reported and DP_TEMP_SET in reported:
        async_add_entities([IntexSpaWaterHeater(coordinator)])


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
    _attr_target_temperature_step = 1.0     # the spa steps in whole degrees Fahrenheit
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
        if not MIN_TEMP_F <= wanted <= MAX_TEMP_F:
            # Silently clamping would leave an automation believing it got what it asked
            # for. The service call should fail instead.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="temperature_out_of_range",
                translation_placeholders={"min": str(MIN_TEMP_F), "max": str(MAX_TEMP_F)},
            )
        await self.coordinator.async_set_dp(DP_TEMP_SET, int(round(wanted)))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, operation_mode != STATE_OFF)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(DP_HEATER, False)
