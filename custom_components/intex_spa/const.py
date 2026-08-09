"""Constants for the Intex Spa integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "intex_spa"

CONF_COUNTRY: Final = "country_code"
CONF_DEVICE_ID: Final = "device_id"
CONF_LOCAL_KEY: Final = "local_key"
CONF_PASSWORD_MD5: Final = "password_md5"
CONF_HOST: Final = "host"
CONF_PROTOCOL: Final = "protocol_version"

DEFAULT_COUNTRY: Final = "40"          # Romania; the app sends the dialling code
DEFAULT_PROTOCOL: Final = "3.5"
DEFAULT_SCAN_INTERVAL: Final = 5       # seconds; a read costs ~15 ms

# --- Intex Link app constants, extracted from the APK; identical for every user ---
# Published in bpietroiu/homeassistant-intex-pool (MIT). The Tuya IoT developer
# route is closed for these devices: the pairing QR is rejected as "designated APP",
# so the app's own OEM credentials are the only way to reach the account.
PACKAGE: Final = "com.intex.spa"
APP_KEY: Final = "mtsv5smaw8gyhws3a5w7"
CH_KEY: Final = "eefe5a0d"
_CERT: Final = "63:D6:FF:87:5B:5D:20:A3:42:DD:15:A9:19:C1:5A:08:58:5A:16:A7:9A:52:7B:F5:ED:81:72:EB:5B:EC:F1:B4"
_SECRET1: Final = "kpuu8s8f43sfsrguehvsyqradgegecef"
_SECRET2: Final = "c49n45ude4scf3jasrnuc8dpsyd3tftm"
SECRET: Final = f"{PACKAGE}_{_CERT}_{_SECRET1}_{_SECRET2}"
TTID: Final = "sdk_international@" + APP_KEY
BASE_URL: Final = "https://a1.tuyaeu.com"
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

SWITCH_DPS: Final = {
    DP_POWER: ("power", "mdi:power"),
    DP_FILTER: ("filtration", "mdi:air-filter"),
    DP_BUBBLES: ("bubbles", "mdi:chart-bubble"),
    DP_JETS: ("jets", "mdi:jets"),
    DP_SANITIZER: ("sanitizer", "mdi:shimmer"),
}

# Product ids known to use the data point layout above. Unknown products are still
# accepted, but only the data points the device actually reports become entities.
KNOWN_PRODUCTS: Final = {"bksofco59ud7eovz"}

# Expressed in Fahrenheit because that is what the device speaks; Home Assistant
# converts for display. Matches the range the panel itself allows, 20-40 C.
MIN_TEMP_F: Final = 68
MAX_TEMP_F: Final = 104
