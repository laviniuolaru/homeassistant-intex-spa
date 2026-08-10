"""Switches for the spa's pumps, heater power and sanitizer."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IntexSpaConfigEntry
from .const import SWITCH_DPS
from .entity import IntexSpaEntity, add_as_they_appear

# The socket thread already serialises the wire; this bounds how much can pile up.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data

    def build(dps, seen):
        new = []
        for dp, (key, icon) in SWITCH_DPS.items():
            if dp in dps and dp not in seen:
                seen.add(dp)
                new.append(IntexSpaSwitch(coordinator, dp, key, icon))
        return new

    add_as_they_appear(coordinator, async_add_entities, build)


class IntexSpaSwitch(IntexSpaEntity, SwitchEntity):
    """One boolean data point."""

    def __init__(self, coordinator, dp: str, key: str, icon: str) -> None:
        super().__init__(coordinator, key)
        self._dp = dp
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool | None:
        value = self.dp(self._dp)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, False)
