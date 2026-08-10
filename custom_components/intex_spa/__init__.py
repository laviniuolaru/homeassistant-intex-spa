"""The Intex Spa integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ESSENTIAL_DPS, KNOWN_PRODUCTS
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
    _check_supported(hass, entry, coordinator.data or {})

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _check_supported(
    hass: HomeAssistant, entry: IntexSpaConfigEntry, dps: dict[str, object]
) -> None:
    """Tell the owner when their spa does not look like the one this was written for.

    Two independent signals. The product id says which model Tuya thinks it is, and the
    set of data points says what it can actually do; a model can be unrecognised and
    still work perfectly, or be recognised and report a layout we cannot use. Neither is
    treated as fatal - whatever is understood still becomes entities - but staying quiet
    would leave someone with half a spa and no idea why.
    """
    issue_id = f"unverified_{entry.entry_id}"
    product = str(entry.data.get("product_id") or "unknown")
    missing = sorted(ESSENTIAL_DPS - set(dps))

    if missing:
        key, severity = "unsupported_layout", ir.IssueSeverity.ERROR
    elif product not in KNOWN_PRODUCTS:
        key, severity = "unverified_model", ir.IssueSeverity.WARNING
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    _LOGGER.warning(
        "This spa (product %s) is not one this integration has been verified against; "
        "data points reported: %s", product, ", ".join(sorted(dps)) or "none",
    )
    ir.async_create_issue(
        hass, DOMAIN, issue_id,
        is_fixable=False,
        severity=severity,
        translation_key=key,
        translation_placeholders={
            "product": product,
            "points": ", ".join(sorted(dps)) or "none",
        },
        learn_more_url="https://github.com/laviniuolaru/homeassistant-intex-spa/issues",
    )


async def async_unload_entry(hass: HomeAssistant, entry: IntexSpaConfigEntry) -> bool:
    """Unload the config entry and release the spa's single local connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded

