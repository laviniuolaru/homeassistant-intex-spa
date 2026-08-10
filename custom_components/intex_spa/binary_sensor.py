"""Whether the heating element is actually drawing power."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import DP_HEAT_STATE, HEAT_STATE_ACTIVE
from .entity import IntexSpaEntity, add_as_they_appear

# Read-only: zero means Home Assistant applies no limit, which is right here.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data

    def build(dps, seen):
        if DP_HEAT_STATE in dps and DP_HEAT_STATE not in seen:
            seen.add(DP_HEAT_STATE)
            return [IntexSpaHeating(coordinator)]
        return []

    add_as_they_appear(coordinator, async_add_entities, build)


class IntexSpaHeating(IntexSpaEntity, BinarySensorEntity):
    """DP 117 is an enum, not a copy of the heater switch.

    With heating enabled it reads "heat" while the water is below target and "warm" once
    it has reached it, so this distinguishes "asked to heat" from "heating right now" -
    which is what you want when working out why the electricity meter moved.
    """

    _attr_translation_key = "heating"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "heating")

    @property
    def is_on(self) -> bool | None:
        value = self.dp(DP_HEAT_STATE)
        return str(value) == HEAT_STATE_ACTIVE if value is not None else None
