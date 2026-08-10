"""Constants for the Intex Spa integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

DOMAIN: Final = "intex_spa"

# Asked for at sign-in, never stored: nothing account-related is kept.
CONF_COUNTRY: Final = "country_code"
CONF_DEVICE_ID: Final = "device_id"
CONF_LOCAL_KEY: Final = "local_key"
CONF_HOST: Final = "host"
CONF_PROTOCOL: Final = "protocol_version"

DEFAULT_COUNTRY: Final = "40"          # Romania; the app sends the dialling code
DEFAULT_PROTOCOL: Final = "3.5"
DEFAULT_SCAN_INTERVAL: Final = 30      # seconds; only a liveness check, updates are pushed

# --- Intex Link app constants: the client identity, identical for every user ---
# Copied from bpietroiu/homeassistant-intex-pool (MIT), which published them; see
# THIRD_PARTY_NOTICES.md. Nothing here was decompiled for this project.
#
# These identify the client, they do not grant access to anything: signing in still
# needs the account holder's own email and password. They are needed because the Tuya
# IoT developer route does not support these devices - it rejects the pairing QR as
# belonging to a "designated APP" - so the information required to interoperate is not
# otherwise available.
PACKAGE: Final = "com.intex.spa"
APP_KEY: Final = "mtsv5smaw8gyhws3a5w7"
CH_KEY: Final = "eefe5a0d"
_CERT: Final = "63:D6:FF:87:5B:5D:20:A3:42:DD:15:A9:19:C1:5A:08:58:5A:16:A7:9A:52:7B:F5:ED:81:72:EB:5B:EC:F1:B4"
_SECRET1: Final = "kpuu8s8f43sfsrguehvsyqradgegecef"
_SECRET2: Final = "c49n45ude4scf3jasrnuc8dpsyd3tftm"
SECRET: Final = f"{PACKAGE}_{_CERT}_{_SECRET1}_{_SECRET2}"
TTID: Final = "sdk_international@" + APP_KEY
BASE_URL: Final = "https://a1.tuyaeu.com"

# Sent as the HTTP User-Agent so the operator can tell this apart from the real app,
# and reach the project if the traffic ever bothers them. The version is read from the
# manifest rather than repeated here, because a second copy only ever goes stale.
def _version() -> str:
    try:
        with open(Path(__file__).parent / "manifest.json", encoding="utf8") as handle:
            return str(json.load(handle).get("version", "unknown"))
    except (OSError, ValueError):
        return "unknown"


USER_AGENT: Final = (
    f"homeassistant-intex-spa/{_version()} "
    "(+https://github.com/laviniuolaru/homeassistant-intex-spa)"
)
APP_VERSION: Final = "1.1.11"

# --- Data points ---
# Verified on product id bksofco59ud7eovz ("SPA PRODUCT WITH SALT & JET").
# Temperatures are transported in whole degrees Fahrenheit regardless of what the
# panel displays, so every read is converted and every write is rounded back.
DP_SANITIZER: Final = "103"
DP_POWER: Final = "104"
DP_JETS: Final = "105"
DP_FILTER: Final = "106"
DP_BUBBLES: Final = "107"
DP_HEATER: Final = "108"
DP_TEMP_SET: Final = "109"
DP_TEMP_CURRENT: Final = "110"
DP_TIMER: Final = "114"
DP_HEAT_STATE: Final = "117"

# DP 117 is an enum, not a mirror of DP 108. Confirmed by experiment: with the
# heater enabled it reads "heat" while the water is below target and "warm" once
# it is at or above it, so it reports whether the element is actually drawing power.
HEAT_STATE_ACTIVE: Final = "heat"
# The full vocabulary, in the order it makes sense to a reader: idle, working, arrived.
HEAT_STATES: Final = ["off", "heat", "warm"]

SWITCH_DPS: Final = {
    DP_POWER: ("power", "mdi:power"),
    DP_FILTER: ("filtration", "mdi:air-filter"),
    DP_BUBBLES: ("bubbles", "mdi:chart-bubble"),
    DP_JETS: ("jets", "mdi:jets"),
    DP_SANITIZER: ("sanitizer", "mdi:shimmer"),
}

# Product ids known to use the data point layout above. The second is listed by
# make-all/tuya-local for the same profile; only the first has been verified here.
# An unknown product is still accepted - entities are created from whatever data points
# the spa actually reports - but the owner is told, so a report can be filed.
KNOWN_PRODUCTS: Final = {"bksofco59ud7eovz", "chsaskllmust5d7a"}

# Without these there is nothing recognisable to control, whatever the product id says.
ESSENTIAL_DPS: Final = {DP_POWER, DP_TEMP_CURRENT}

# Expressed in Fahrenheit because that is what the device speaks; Home Assistant
# converts for display. Matches the range the panel itself allows, 20-40 C.
MIN_TEMP_F: Final = 68
MAX_TEMP_F: Final = 104
