"""Config flow: the user types their Intex Link email and password, nothing else.

Everything the integration needs afterwards - device id, local key, LAN address - is
looked up automatically. The address is found by listening for the spa's own beacons,
and only if it stays silent is the user asked to type one.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .cloud import (
    IntexAuthError,
    IntexCloud,
    IntexCloudError,
    new_client_id,
    password_digest,
)
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
from .discovery import as_address, find_host
from .probe import PROTOCOL_VERSIONS, probe_protocol

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
    vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
})


class IntexSpaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setting up an Intex spa."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> IntexSpaOptionsFlow:
        return IntexSpaOptionsFlow()

    def __init__(self) -> None:
        self._devices: list[dict[str, Any]] = []
        self._chosen: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud = IntexCloud(async_get_clientsession(self.hass), new_client_id())
            try:
                await cloud.login(
                    user_input[CONF_EMAIL],
                    password_digest(user_input[CONF_PASSWORD]),
                    user_input[CONF_COUNTRY],
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
                    # Nothing from the sign-in is kept: the credentials exist only for
                    # as long as this flow runs, and what gets written to disk is the
                    # device key needed for local control and nothing else.
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
        errors: dict[str, str] = {}
        if user_input is not None:
            # Must be a literal address: a hostname here would defeat the same
            # protection that stops a forged beacon naming an off-network target.
            host = as_address(user_input[CONF_HOST])
            if host:
                return await self._create(self._chosen, host)
            errors["base"] = "invalid_host"

        return self.async_show_form(
            step_id="host",
            errors=errors,
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            description_placeholders={"name": self._chosen.get("name", "spa")},
        )

    async def _async_finish(self, device: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(device["device_id"])
        # Re-running setup for a spa that is already added is a reasonable way to fix a
        # stale address or key, so hand over what was just fetched rather than refusing.
        self._abort_if_unique_id_configured(
            updates={CONF_LOCAL_KEY: device["local_key"]}, reload_on_update=True
        )

        if device["product_id"] and device["product_id"] not in KNOWN_PRODUCTS:
            _LOGGER.info(
                "Product id %s has not been verified with this integration; entities are "
                "created from whatever data points the spa reports",
                device["product_id"],
            )

        self._chosen = device
        host = await find_host(self.hass, device["device_id"])
        if not host:
            return await self.async_step_host()
        return await self._create(device, host)

    async def _create(self, device: dict[str, Any], host: str) -> ConfigFlowResult:
        # Ask the spa which protocol it speaks rather than assuming. Assuming is what
        # leaves someone with an older module in an unbreakable loop: the wrong version
        # looks exactly like a rotated key, and re-adding writes the same wrong guess.
        answer = await self.hass.async_add_executor_job(
            probe_protocol, device["device_id"], host, device["local_key"]
        )
        protocol = answer[0] if answer else DEFAULT_PROTOCOL
        if not answer:
            _LOGGER.warning(
                "No protocol version answered at %s; storing %s. If the spa stays "
                "unavailable, change it in the integration options", host, protocol,
            )

        return self.async_create_entry(
            title=device["name"],
            data={
                CONF_DEVICE_ID: device["device_id"],
                CONF_LOCAL_KEY: device["local_key"],
                CONF_HOST: host,
                CONF_PROTOCOL: protocol,
                "product_id": device["product_id"],
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The spa stopped accepting its key, which only a fresh sign-in can replace."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud = IntexCloud(async_get_clientsession(self.hass), new_client_id())
            try:
                await cloud.login(
                    user_input[CONF_EMAIL],
                    password_digest(user_input[CONF_PASSWORD]),
                    user_input[CONF_COUNTRY],
                )
                key = await cloud.local_key_for(entry.data[CONF_DEVICE_ID])
            except IntexAuthError:
                errors["base"] = "invalid_auth"
            except IntexCloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while signing in again")
                errors["base"] = "unknown"
            else:
                if key is None:
                    # The credentials work, but this account does not own this spa.
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, CONF_LOCAL_KEY: key}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=CREDENTIALS_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )


class IntexSpaOptionsFlow(OptionsFlow):
    """Lets the address and protocol version be corrected after setup.

    Without this, a spa the probe could not reach - or one that later moves somewhere
    discovery cannot see - can only be fixed by deleting the entry and losing its
    history. The local key is here too because re-pairing rotates it and someone may
    already have the new one to hand.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            host = as_address(user_input[CONF_HOST])
            if not host:
                errors["base"] = "invalid_host"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: host,
                        CONF_PROTOCOL: user_input[CONF_PROTOCOL],
                        CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY].strip()
                        or entry.data[CONF_LOCAL_KEY],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Required(
                    CONF_PROTOCOL, default=entry.data.get(CONF_PROTOCOL, DEFAULT_PROTOCOL)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(PROTOCOL_VERSIONS), mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_LOCAL_KEY, default=""): str,
            }),
        )
