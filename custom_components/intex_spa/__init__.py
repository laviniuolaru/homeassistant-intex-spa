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

def _quieten_tinytuya() -> None:
    """Keep the local key out of debug logs, without overruling the user.

    tinytuya prints the key at debug level, and debug logs are what people paste into
    public issues. Only clamp it when no level has been set explicitly, so anyone who
    asks for tinytuya debug in configuration.yaml still gets it.
    """
    logger = logging.getLogger("tinytuya")
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)


async def async_setup_entry(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> bool:
    """Set up the spa from a config entry."""
    _quieten_tinytuya()
    coordinator = IntexSpaCoordinator(hass, entry)
    # The socket thread has to be running before anything can be asked of the spa.
    await coordinator.async_start()
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # A failed setup is never unloaded, so nothing else would ever stop the thread.
        # Home Assistant retries with backoff, and each attempt would leave another one
        # behind, all dialling a spa that accepts a single connection.
        await coordinator.async_shutdown()
        raise
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> bool:
    """Unload the config entry and release the spa's single local connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded

