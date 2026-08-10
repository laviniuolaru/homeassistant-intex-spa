"""Diagnostics, with everything that could unlock the spa or the account removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import IntexSpaConfigEntry
from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY

# Nothing about the Intex account is stored any more, but an entry that has not been
# migrated yet may still carry the old fields, and a diagnostics dump is the one place
# they would be handed to someone else.
REDACT = {
    CONF_LOCAL_KEY, CONF_DEVICE_ID,
    "email", "password", "password_md5", "country_code", "client_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IntexSpaConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        # The raw data points are the useful part of a bug report: they are what decides
        # which entities exist and how a model differs from the one that was verified.
        "data_points": dict(coordinator.data or {}),
        "connected": coordinator.link_connected,
        "last_update_success": coordinator.last_update_success,
    }
