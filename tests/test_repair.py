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
    """Returns an error until the local key it was built with matches the real one."""

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

    def _ok(self):
        return self.key == self.real_key and self.address == self.real_host

    replies = None      # when set, a list of payloads to hand out in order

    def status(self):
        if not self._ok():
            return {"Err": "914", "Error": "decrypt failed"}
        if FakeDevice.replies:
            return FakeDevice.replies.pop(0)
        return {"dps": {"110": 90}}

    def set_value(self, dp, value, nowait=False):
        return {"dps": {dp: value}} if self._ok() else {"Err": "914", "Error": "decrypt failed"}


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


class Hass:
    def __init__(self):
        self.config_entries = types.SimpleNamespace(
            async_update_entry=lambda entry, data: setattr(entry, "data", data)
        )

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def build(key="OLDKEY", host="192.168.1.133"):
    entry = Entry({
        "email": "a@b.c", "password_md5": "d41d8cd98f00b204e9800998ecf8427e",
        "country_code": "40", "client_id": "cid",
        "device_id": "dev", "local_key": key, "host": host, "protocol_version": "3.5",
    })
    return mod.IntexSpaCoordinator(Hass(), entry), entry


class FakeCloud:
    """Counts calls so the rate limiting can be checked too.

    Hands out `serves` rather than whatever the device wants, so a scenario where the
    cloud cannot actually fix the problem can be expressed.
    """
    logins = 0
    serves = "NEWKEY"

    def __init__(self, session, client_id):
        pass

    async def login(self, email, password, country):
        FakeCloud.logins += 1

    async def local_key_for(self, device_id):
        return FakeCloud.serves


mod.IntexCloud = FakeCloud
results = []


def check(name, condition, detail=""):
    results.append(condition)
    print(f"  {'OK   ' if condition else 'FAIL'} {name}{'  ' + detail if detail else ''}")


async def main():
    # 1. rotated key is fetched and stored, and the poll still succeeds
    FakeCloud.logins = 0
    coord, entry = build(key="OLDKEY")
    data = await coord._async_update_data()
    check("rotated key is repaired in one cycle", data == {"110": 90}, str(data))
    check("the new key is written to the config entry", entry.data["local_key"] == "NEWKEY")
    check("exactly one cloud sign-in happened", FakeCloud.logins == 1, f"logins={FakeCloud.logins}")

    # 2. healthy device must not touch the cloud at all
    FakeCloud.logins = 0
    coord, _ = build(key="NEWKEY")
    await coord._async_update_data()
    check("a healthy connection never calls the cloud", FakeCloud.logins == 0)

    # 3. moved device is rediscovered
    FakeCloud.logins = 0
    coord, entry = build(key="NEWKEY", host="192.168.1.99")
    mod.find_host = lambda hass, device_id, timeout=20.0: _async_return("192.168.1.133")
    data = await coord._async_update_data()
    check("a moved device is rediscovered", entry.data["host"] == "192.168.1.133", str(data))

    # 4. commands repair too, instead of failing the first press
    FakeCloud.logins = 0
    coord, entry = build(key="OLDKEY")
    await coord.async_set_dp("107", True)
    check("a command repairs and then succeeds", entry.data["local_key"] == "NEWKEY")
    check("the command scheduled a confirmation", coord._confirm_cancel is not None)

    # 5. a failure the cloud cannot fix gives up instead of looping
    FakeCloud.logins = 0
    FakeDevice.real_key = "UNREACHABLE"       # the cloud still only serves NEWKEY
    coord, _ = build(key="OLDKEY")
    try:
        await coord._async_update_data()
        check("an unfixable failure raises UpdateFailed", False, "nothing was raised")
    except UpdateFailed as err:
        check("an unfixable failure raises UpdateFailed", True, str(err)[:44])
    check("the cloud was not hammered in a loop", FakeCloud.logins <= 1, f"logins={FakeCloud.logins}")
    FakeDevice.real_key = "NEWKEY"

    # 6. partial payloads must merge, not wipe what was already known
    FakeDevice.replies = [
        {"dps": {"104": True, "106": False, "110": 90}},   # full picture
        {"dps": {"106": True}},                            # only what changed
        {},                                                # nothing changed at all
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

    # 7. a write shows up immediately, without waiting for the next poll
    coord, _ = build(key="NEWKEY")
    await coord._async_update_data()
    await coord.async_set_dp("107", True)
    check("a write is reflected at once", coord.data.get("107") is True, str(coord.data))

    # 8. a pushed update merges and is published without any polling
    coord, _ = build(key="NEWKEY")
    await coord._async_update_data()
    coord._apply_push({"107": True})
    check("a pushed update merges into the state", coord.data.get("107") is True, str(coord.data))
    check("a push keeps the points it did not mention", coord.data.get("110") == 90)

    # 9. a rotated key rebuilds the connection rather than reusing a dead socket
    coord, _ = build(key="OLDKEY")
    await coord._async_update_data()
    check("the link was rebuilt after the key changed", coord._link.rebuilds >= 1,
          f"rebuilds={coord._link.rebuilds}")

    # 10. cooldown blocks a second cloud lookup soon after the first
    FakeCloud.logins = 0
    coord, _ = build(key="OLDKEY")
    await coord._async_update_data()
    coord.entry.data = {**coord.entry.data, "local_key": "OLDKEY"}
    coord._link.rebuild()
    try:
        await coord._async_update_data()
    except UpdateFailed:
        pass
    check("the cooldown blocks a second sign-in", FakeCloud.logins == 1,
          f"logins={FakeCloud.logins}")


async def _async_return(value):
    return value


asyncio.run(main())
print("\n" + ("ALL PASSED" if all(results) else "THERE WERE FAILURES"))
sys.exit(0 if all(results) else 1)
