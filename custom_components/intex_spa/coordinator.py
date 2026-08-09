"""Owns the single local connection to the spa and keeps the local key valid.

The spa accepts exactly one local client at a time, so everything funnels through one
coordinator. tinytuya is synchronous, so every call is pushed to the executor.

The interesting part is recovery. Re-pairing the spa in the Intex Link app rotates the
local key, which silently breaks the LAN connection and normally means editing the
integration by hand. Here a decrypt failure triggers a cloud lookup, the fresh key is
written back to the config entry, and the connection is rebuilt.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

import tinytuya
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import IntexAuthError, IntexCloud, IntexCloudError
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .discovery import find_host

_LOGGER = logging.getLogger(__name__)

# tinytuya reports a decrypt/version mismatch as 914 and a bad payload as 904. Either can
# mean the key was rotated, so both are worth one cloud lookup.
KEY_ERRORS = frozenset({"914", "904"})

# Never ask the cloud more than this often, however badly the LAN side is failing.
KEY_REFRESH_COOLDOWN = 600.0
HOST_REDISCOVER_COOLDOWN = 300.0


class IntexSpaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the spa over the LAN and repairs the connection when it breaks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self._device: tinytuya.Device | None = None
        self._last_key_refresh = 0.0
        self._last_host_lookup = 0.0

    # --- connection ----------------------------------------------------------------

    def _build_device(self) -> tinytuya.Device:
        """Construct the tinytuya client. Runs in the executor: it opens a socket."""
        data = self.entry.data
        device = tinytuya.Device(
            dev_id=data[CONF_DEVICE_ID],
            address=data[CONF_HOST],
            local_key=data[CONF_LOCAL_KEY],
            persist=True,
        )
        device.set_version(float(data[CONF_PROTOCOL]))
        device.set_socketTimeout(5)
        device.set_socketRetryLimit(1)
        return device

    async def _async_device(self) -> tinytuya.Device:
        if self._device is None:
            self._device = await self.hass.async_add_executor_job(self._build_device)
        return self._device

    def _drop_device(self) -> None:
        device, self._device = self._device, None
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001 - closing a dead socket must never raise
                pass

    # --- recovery ------------------------------------------------------------------

    async def _refresh_local_key(self) -> bool:
        """Ask the cloud for the current key. True when it changed and was stored."""
        now = time.monotonic()
        if now - self._last_key_refresh < KEY_REFRESH_COOLDOWN:
            return False
        self._last_key_refresh = now

        data = self.entry.data
        cloud = IntexCloud(async_get_clientsession(self.hass), data["client_id"])
        try:
            await cloud.login(data["email"], data["password"], data[CONF_COUNTRY])
            key = await cloud.local_key_for(data[CONF_DEVICE_ID])
        except IntexAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except IntexCloudError as err:
            _LOGGER.debug("Could not reach the cloud to refresh the local key: %s", err)
            return False

        if not key or key == data[CONF_LOCAL_KEY]:
            return False

        _LOGGER.info("The spa's local key changed; reconnecting with the new one")
        self.hass.config_entries.async_update_entry(
            self.entry, data={**data, CONF_LOCAL_KEY: key}
        )
        self._drop_device()
        return True

    async def _rediscover_host(self) -> bool:
        """Re-find the spa on the LAN. True when the address changed and was stored."""
        now = time.monotonic()
        if now - self._last_host_lookup < HOST_REDISCOVER_COOLDOWN:
            return False
        self._last_host_lookup = now

        host = await find_host(self.entry.data[CONF_DEVICE_ID])
        if not host or host == self.entry.data[CONF_HOST]:
            return False

        _LOGGER.info("The spa moved to %s; reconnecting", host)
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_HOST: host}
        )
        self._drop_device()
        return True

    # --- polling -------------------------------------------------------------------

    async def _async_repair(self, error: str) -> bool:
        """Try once to make the connection work again. True when something changed.

        Ordered by likelihood: a decrypt failure means the key almost certainly rotated,
        anything else is more often the spa having moved to a new address.
        """
        if error in KEY_ERRORS:
            return await self._refresh_local_key() or await self._rediscover_host()
        return await self._rediscover_host() or await self._refresh_local_key()

    def _read_status(self, device: tinytuya.Device) -> dict[str, Any]:
        return device.status() or {}

    async def _async_update_data(self) -> dict[str, Any]:
        last: str = "no response"

        for attempt in (1, 2):
            device = await self._async_device()
            try:
                status = await self.hass.async_add_executor_job(self._read_status, device)
            except Exception as err:  # noqa: BLE001 - tinytuya raises bare exceptions
                # A raised socket error is as good a repair trigger as a returned one,
                # so fall through instead of giving up on this cycle.
                self._drop_device()
                status, last = {}, str(err)
            else:
                dps = status.get("dps")
                if isinstance(dps, dict) and dps:
                    return dps
                last = str(status.get("Error") or status.get("Err") or "no data points")

            _LOGGER.debug("Spa gave nothing back (attempt %d): %s", attempt, last)
            if attempt == 2 or not await self._async_repair(str(status.get("Err", ""))):
                break

        raise UpdateFailed(f"the spa did not return any data: {last}")

    # --- writing -------------------------------------------------------------------

    def _write(self, device: tinytuya.Device, dp: str, value: Any) -> dict[str, Any]:
        return device.set_value(dp, value, nowait=False) or {}

    async def async_set_dp(self, dp: str, value: Any) -> None:
        """Set one data point, then refresh so the UI reflects reality rather than hope.

        Repairs on the same terms as polling. Without this, the first press of a button
        after the key rotated would fail with an error toast even though the next poll
        would have fixed things seconds later.
        """
        last: str = "no response"

        for attempt in (1, 2):
            device = await self._async_device()
            try:
                result = await self.hass.async_add_executor_job(self._write, device, dp, value)
            except Exception as err:  # noqa: BLE001
                self._drop_device()
                result, last = {"Err": ""}, str(err)
            else:
                if not result.get("Err"):
                    await self.async_request_refresh()
                    return
                last = str(result.get("Error") or result.get("Err"))

            if attempt == 2 or not await self._async_repair(str(result.get("Err", ""))):
                break

        raise HomeAssistantError(f"the spa did not accept the command: {last}")

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.hass.async_add_executor_job(self._drop_device)
