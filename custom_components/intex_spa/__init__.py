"""The Intex Spa integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import IntexSpaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.WATER_HEATER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

type IntexSpaConfigEntry = ConfigEntry[IntexSpaCoordinator]

# tinytuya writes the local key into its logs at debug level. Nothing here needs that,
# and a debug log is something users paste into public issues.
logging.getLogger("tinytuya").setLevel(logging.INFO)


async def async_setup_entry(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> bool:
    """Set up the spa from a config entry."""
    coordinator = IntexSpaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> bool:
    """Unload the config entry and release the spa's single local connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
