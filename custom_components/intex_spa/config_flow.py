"""Config flow: the user types their Intex Link email and password, nothing else.

Everything the integration needs afterwards - device id, local key, LAN address - is
looked up automatically. The address is found by listening for the spa's own beacons,
and only if it stays silent is the user asked to type one.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import IntexAuthError, IntexCloud, IntexCloudError, new_client_id
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL,
    DEFAULT_COUNTRY,
    DEFAULT_PROTOCOL,
    DOMAIN,
    KNOWN_PRODUCTS,
)
from .discovery import find_host

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
    vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
})


class IntexSpaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setting up an Intex spa."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._devices: list[dict[str, Any]] = []
        self._chosen: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = new_client_id()
            cloud = IntexCloud(async_get_clientsession(self.hass), client_id)
            try:
                await cloud.login(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD], user_input[CONF_COUNTRY]
                )
                devices = await cloud.devices()
            except IntexAuthError:
                errors["base"] = "invalid_auth"
            except IntexCloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while talking to the Intex cloud")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._credentials = {**user_input, "client_id": client_id}
                    self._devices = devices
                    if len(devices) == 1:
                        return await self._async_finish(devices[0])
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=CREDENTIALS_SCHEMA, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which device to add when the account holds more than one."""
        if user_input is not None:
            chosen = next(
                d for d in self._devices if d["device_id"] == user_input[CONF_DEVICE_ID]
            )
            return await self._async_finish(chosen)

        options = [
            {"value": d["device_id"], "label": f"{d['name']} ({d['device_id'][-6:]})"}
            for d in self._devices
        ]
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }),
        )

    async def async_step_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Only reached when the spa never announced itself on the network."""
        if user_input is not None:
            return self._create(self._chosen, user_input[CONF_HOST])

        return self.async_show_form(
            step_id="host",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            description_placeholders={"name": self._chosen.get("name", "spa")},
        )

    async def _async_finish(self, device: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(device["device_id"])
        self._abort_if_unique_id_configured()

        if device["product_id"] and device["product_id"] not in KNOWN_PRODUCTS:
            _LOGGER.info(
                "Product id %s has not been verified with this integration; entities are "
                "created from whatever data points the spa reports",
                device["product_id"],
            )

        self._chosen = device
        host = await find_host(device["device_id"])
        if not host:
            return await self.async_step_host()
        return self._create(device, host)

    def _create(self, device: dict[str, Any], host: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=device["name"],
            data={
                CONF_EMAIL: self._credentials[CONF_EMAIL],
                CONF_PASSWORD: self._credentials[CONF_PASSWORD],
                CONF_COUNTRY: self._credentials[CONF_COUNTRY],
                "client_id": self._credentials["client_id"],
                CONF_DEVICE_ID: device["device_id"],
                CONF_LOCAL_KEY: device["local_key"],
                CONF_HOST: host,
                CONF_PROTOCOL: DEFAULT_PROTOCOL,
                "product_id": device["product_id"],
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """The stored password stopped working - most likely it was changed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud = IntexCloud(async_get_clientsession(self.hass), entry.data["client_id"])
            try:
                await cloud.login(
                    entry.data[CONF_EMAIL], user_input[CONF_PASSWORD], entry.data[CONF_COUNTRY]
                )
                key = await cloud.local_key_for(entry.data[CONF_DEVICE_ID])
            except IntexAuthError:
                errors["base"] = "invalid_auth"
            except IntexCloudError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        **({CONF_LOCAL_KEY: key} if key else {}),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }),
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )
