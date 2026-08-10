"""Exercise the coordinator's self-repair without Home Assistant or a real spa.

Only the framework is faked. The state machine under test - when to ask the cloud for a
new key, when to look for a new address, when to give up - is the real one.
"""
import asyncio
import concurrent.futures
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "custom_components"))


# --- fake framework ---------------------------------------------------------------
def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__path__ = []          # make it importable as a package, so submodules resolve
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Enum(str):
    """Stands in for the HA string enums the platforms import."""

    def __getattr__(self, item):
        return f"{item.lower()}"


class UpdateFailed(Exception):
    pass


class HomeAssistantError(Exception):
    pass


class ConfigEntryAuthFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __class_getitem__(cls, item):   # the real one is generic
        return cls

    def __init__(self, hass, logger, name=None, update_interval=None, always_update=True):
        self.hass = hass
        self.data = None
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1

    def async_set_updated_data(self, data):
        self.data = data

    async def async_shutdown(self):
        pass


class FakeDevice:
    """Answers only when both the address and the key it was built with are right."""

    real_key = "NEWKEY"
    real_host = "192.168.1.133"

    def __init__(self, dev_id, address, local_key, persist=False):
        self.key, self.address = local_key, address

    def set_version(self, v):
        pass

    def set_socketTimeout(self, v):
        pass

    def set_socketRetryLimit(self, v):
        pass

    def close(self):
        pass

    replies = None      # when set, a list of payloads to hand out in order

    def _fault(self):
        """A wrong address and a wrong key fail differently, as on real hardware.

        A wrong address never reaches anything, so it is an unreachable error. 914 means
        the session-key handshake was answered and refused, which needs a device there.
        """
        if self.address != self.real_host:
            return {"Err": "905", "Error": "device unreachable"}
        if self.key != self.real_key:
            return {"Err": "914", "Error": "decrypt failed"}
        return None

    def status(self):
        fault = self._fault()
        if fault:
            return fault
        if FakeDevice.replies:
            return FakeDevice.replies.pop(0)
        return {"dps": {"110": 90}}

    def set_value(self, dp, value, nowait=False):
        return self._fault() or {"dps": {dp: value}}


_mod("tinytuya", Device=FakeDevice)
_mod("aiohttp", ClientError=Exception, ClientSession=object)
_mod("homeassistant")
_mod("homeassistant.const", Platform=_Enum(), CONF_EMAIL="email", CONF_PASSWORD="password",
     ATTR_TEMPERATURE="temperature", STATE_OFF="off", UnitOfTemperature=_Enum(),
     UnitOfTime=_Enum(), EntityCategory=_Enum())
_mod("homeassistant.config_entries", ConfigEntry=dict)
_mod("homeassistant.core", HomeAssistant=object, CALLBACK_TYPE=object,
     callback=lambda fn: fn)
_mod("homeassistant.exceptions", ConfigEntryAuthFailed=ConfigEntryAuthFailed,
     HomeAssistantError=HomeAssistantError)
_mod("homeassistant.helpers")
_mod("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
_mod("homeassistant.helpers.event", async_call_later=lambda hass, delay, cb: (lambda: None))
_mod("homeassistant.helpers.update_coordinator",
     DataUpdateCoordinator=DataUpdateCoordinator, UpdateFailed=UpdateFailed)

from intex_spa import coordinator as mod  # noqa: E402


class FakeLink:
    """Runs jobs inline so the tests stay deterministic and thread-free."""

    def __init__(self, build_device, on_push, on_state):
        self._build = build_device
        self.on_push = on_push
        self.on_state = on_state
        self.device = None
        self.rebuilds = 0
        self.connected = True

    def start(self):
        pass

    def stop(self):
        pass

    def rebuild(self):
        self.rebuilds += 1
        self.device = None

    def submit(self, func):
        future = concurrent.futures.Future()
        if self.device is None:
            self.device = self._build()
        try:
            future.set_result(func(self.device))
        except Exception as err:  # noqa: BLE001
            future.set_exception(err)
        return future


mod.SpaLink = FakeLink


class Entry:
    def __init__(self, data):
        self.data = data
        self.title = "Spa"
        self.reauths = 0

    def async_start_reauth(self, hass):
        self.reauths += 1


class Hass:
    def __init__(self):
        self.config_entries = types.SimpleNamespace(
            async_update_entry=lambda entry, data: setattr(entry, "data", data)
        )

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def build(key="OLDKEY", host="192.168.1.133"):
    entry = Entry({
        "device_id": "dev", "local_key": key, "host": host, "protocol_version": "3.5",
    })
    return mod.IntexSpaCoordinator(Hass(), entry), entry


results = []


def check(name, condition, detail=""):
    results.append(condition)
    print(f"  {'OK   ' if condition else 'FAIL'} {name}{'  ' + detail if detail else ''}")


async def main():
    # 1. the happy path
    coord, _ = build(key="NEWKEY")
    data = await coord._async_update_data()
    check("a healthy poll returns the data points", data == {"110": 90}, str(data))

    # 2. a rotated key cannot be repaired here on purpose: nothing about the account is
    #    stored, so the only way out is asking the owner to sign in again
    coord, entry = build(key="OLDKEY")
    try:
        await coord._async_update_data()
        check("a rotated key asks for a fresh sign-in", False, "nothing was raised")
    except ConfigEntryAuthFailed:
        check("a rotated key asks for a fresh sign-in", True)
    check("the stored key was left alone", entry.data["local_key"] == "OLDKEY")

    # 3. the same from a command, where Home Assistant would not start reauth by itself
    coord, entry = build(key="OLDKEY")
    try:
        await coord.async_set_dp("107", True)
    except Exception:  # noqa: BLE001
        pass
    check("a command also asks for a fresh sign-in", entry.reauths == 1,
          f"reauths={entry.reauths}")

    # 4. a moved device is still repaired without anyone signing in
    coord, entry = build(key="NEWKEY", host="192.168.1.99")
    mod.find_host = lambda hass, device_id, timeout=20.0: _async_return("192.168.1.133")
    data = await coord._async_update_data()
    check("a moved device is rediscovered", entry.data["host"] == "192.168.1.133", str(data))

    # 5. partial and empty replies must not wipe what is known
    FakeDevice.replies = [
        {"dps": {"104": True, "106": False, "110": 90}},
        {"dps": {"106": True}},
        {},
    ]
    coord, _ = build(key="NEWKEY")
    first = await coord._async_update_data()
    check("first poll keeps every point", first == {"104": True, "106": False, "110": 90}, str(first))
    second = await coord._async_update_data()
    check("a partial reply merges instead of wiping",
          second == {"104": True, "106": True, "110": 90}, str(second))
    third = await coord._async_update_data()
    check("an empty reply keeps the last known state",
          third == {"104": True, "106": True, "110": 90}, str(third))
    FakeDevice.replies = None

    # 6. a write shows immediately, and a push merges
    coord, _ = build(key="NEWKEY")
    await coord._async_update_data()
    await coord.async_set_dp("107", True)
    check("a write is reflected at once", coord.data.get("107") is True, str(coord.data))
    coord._apply_push({"105": True})
    check("a pushed update merges into the state", coord.data.get("105") is True, str(coord.data))
    check("a push keeps the points it did not mention", coord.data.get("110") == 90)

    # 7. an unreachable spa fails the update rather than serving stale values
    FakeDevice.real_host = "192.168.1.1"
    mod.find_host = lambda hass, device_id, timeout=20.0: _async_return(None)
    coord, _ = build(key="NEWKEY")
    try:
        await coord._async_update_data()
        check("an unreachable spa raises UpdateFailed", False, "nothing was raised")
    except UpdateFailed as err:
        check("an unreachable spa raises UpdateFailed", True, str(err)[:40])
    FakeDevice.real_host = "192.168.1.133"

    # 8. the account is genuinely gone from the stored data
    _, entry = build(key="NEWKEY")
    leaked = [k for k in entry.data if k in ("email", "password", "password_md5", "client_id")]
    check("no account data is stored at all", not leaked, str(leaked))


async def _async_return(value):
    return value


asyncio.run(main())
print("\n" + ("ALL PASSED" if all(results) else "THERE WERE FAILURES"))
sys.exit(0 if all(results) else 1)
