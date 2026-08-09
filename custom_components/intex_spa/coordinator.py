"""Keeps the spa's state current and its credentials valid.

Updates arrive by push: a background thread holds the local connection open and the spa
announces changes as they happen, including ones made from the Intex Link app. The
periodic poll that remains is a liveness check, not the main source of data.

The other job here is recovery. Re-pairing the spa in the Intex Link app rotates the
local key, which silently breaks the LAN connection and normally means editing the
integration by hand. A decrypt failure triggers a cloud lookup, the fresh key is written
back to the config entry, and the connection is rebuilt.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

import tinytuya
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud import IntexAuthError, IntexCloud, IntexCloudError
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PASSWORD_MD5,
    CONF_PROTOCOL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .discovery import find_host
from .link import SpaLink

_LOGGER = logging.getLogger(__name__)

# tinytuya reports a decrypt/version mismatch as 914 and a bad payload as 904. Either can
# mean the key was rotated, so both are worth one cloud lookup.
KEY_ERRORS = frozenset({"914", "904"})

# Never ask the cloud more than this often, however badly the LAN side is failing.
KEY_REFRESH_COOLDOWN = 600.0
HOST_REDISCOVER_COOLDOWN = 300.0

# How long to let the spa settle before re-reading after a write.
CONFIRM_DELAY = 2.0

# How long a command may wait for the socket thread before it is treated as stuck.
COMMAND_TIMEOUT = 15.0


class IntexSpaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the accumulated data point state and repairs the connection when it breaks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Pushes carry the news; this is only a liveness check.
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self._last_key_refresh = 0.0
        self._last_host_lookup = 0.0
        self._confirm_cancel: CALLBACK_TYPE | None = None
        # Accumulated view of the spa. Tuya answers with only the data points that
        # changed, so replacing this wholesale would make every absent point read as
        # unknown and entities would flicker between their real value and blank.
        self._dps: dict[str, Any] = {}
        self._link = SpaLink(self._build_device, self._push_from_thread, self._state_from_thread)

    # --- connection ----------------------------------------------------------------

    def _build_device(self) -> tinytuya.Device:
        """Construct the tinytuya client. Runs on the link thread: it opens a socket."""
        data = self.entry.data
        device = tinytuya.Device(
            dev_id=data[CONF_DEVICE_ID],
            address=data[CONF_HOST],
            local_key=data[CONF_LOCAL_KEY],
            persist=True,
        )
        device.set_version(float(data[CONF_PROTOCOL]))
        return device

    async def async_start(self) -> None:
        await self.hass.async_add_executor_job(self._link.start)

    async def async_shutdown(self) -> None:
        if self._confirm_cancel is not None:
            self._confirm_cancel()
            self._confirm_cancel = None
        await super().async_shutdown()
        await self.hass.async_add_executor_job(self._link.stop)

    # --- callbacks from the link thread ---------------------------------------------

    def _push_from_thread(self, dps: dict[str, Any]) -> None:
        self.hass.loop.call_soon_threadsafe(self._apply_push, dps)

    @callback
    def _apply_push(self, dps: dict[str, Any]) -> None:
        self._dps.update(dps)
        self.async_set_updated_data(dict(self._dps))

    def _state_from_thread(self, connected: bool, detail: str) -> None:
        if connected:
            _LOGGER.debug("Connected to the spa")
        else:
            _LOGGER.debug("Disconnected from the spa: %s", detail)

    async def _async_run(self, func) -> Any:
        """Run something on the socket thread and wait for it."""
        future = self._link.submit(func)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), COMMAND_TIMEOUT)
        except TimeoutError as err:
            future.cancel()
            raise ConnectionError("the spa did not answer in time") from err

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
            await cloud.login(data["email"], data[CONF_PASSWORD_MD5], data[CONF_COUNTRY])
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
        self._link.rebuild()
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
        self._link.rebuild()
        return True

    async def _async_repair(self, error: str) -> bool:
        """Try once to make the connection work again. True when something changed.

        Ordered by likelihood: a decrypt failure means the key almost certainly rotated,
        anything else is more often the spa having moved to a new address.
        """
        if error in KEY_ERRORS:
            return await self._refresh_local_key() or await self._rediscover_host()
        return await self._rediscover_host() or await self._refresh_local_key()

    # --- polling -------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        last: str = "no response"

        for attempt in (1, 2):
            status: dict[str, Any] = {}
            try:
                status = await self._async_run(lambda device: device.status() or {})
            except Exception as err:  # noqa: BLE001 - tinytuya raises bare exceptions
                last = str(err)
            else:
                dps = status.get("dps")
                if isinstance(dps, dict) and dps:
                    self._dps.update(dps)
                    return dict(self._dps)
                # An empty reply is normal once nothing has changed, as long as a full
                # picture was seen at least once.
                if self._dps and not status.get("Err"):
                    return dict(self._dps)
                last = str(status.get("Error") or status.get("Err") or "no data points")

            _LOGGER.debug("Spa gave nothing back (attempt %d): %s", attempt, last)
            if attempt == 2 or not await self._async_repair(str(status.get("Err", ""))):
                break

        raise UpdateFailed(f"the spa did not return any data: {last}")

    # --- writing -------------------------------------------------------------------

    def _schedule_confirmation(self) -> None:
        """Re-read a couple of seconds after a write, once the spa has caught up."""
        if self._confirm_cancel is not None:
            self._confirm_cancel()

        async def _confirm(_now) -> None:
            self._confirm_cancel = None
            await self.async_request_refresh()

        self._confirm_cancel = async_call_later(self.hass, CONFIRM_DELAY, _confirm)

    async def async_set_dp(self, dp: str, value: Any) -> None:
        """Set one data point and show it at once, rather than waiting to be told."""
        last: str = "no response"

        for attempt in (1, 2):
            result: dict[str, Any] = {}
            try:
                result = await self._async_run(
                    lambda device: device.set_value(dp, value, nowait=False) or {}
                )
            except Exception as err:  # noqa: BLE001
                last = str(err)
            else:
                if not result.get("Err"):
                    # Order matters: the spa often echoes its previous state in the
                    # reply, so what was asked for is applied last and wins.
                    if isinstance(result.get("dps"), dict):
                        self._dps.update(result["dps"])
                    self._dps[dp] = value
                    self.async_set_updated_data(dict(self._dps))
                    self._schedule_confirmation()
                    return
                last = str(result.get("Error") or result.get("Err"))

            if attempt == 2 or not await self._async_repair(str(result.get("Err", ""))):
                break

        raise HomeAssistantError(f"the spa did not accept the command: {last}")
