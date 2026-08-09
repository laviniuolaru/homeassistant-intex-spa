"""Find a Tuya device's LAN address by listening to the beacons it already broadcasts.

Tuya devices announce themselves every few seconds on UDP. The cloud hands us the
device id but not its address, so this is what saves the user from having to find and
type an IP. Three dialects exist in the wild and all three are handled:

  6666  plaintext JSON
  6667  AES-ECB, fixed key shared by every Tuya device
  7000  AES-GCM, same key, used by protocol 3.5 firmware
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
import struct
from typing import Any

import tinytuya
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Not a secret: this key is compiled into every Tuya device and published widely.
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()

PORTS = (6666, 6667, 7000)

# A beacon is unauthenticated: the encrypted dialects use a key published in every Tuya
# device, and anything on the LAN can send one. Nothing here may be trusted beyond
# "somebody at this address claims to be this device id".
MAX_BEACONS = 512
PREFIX_55AA = 0x000055AA
PREFIX_6699 = 0x00006699


def _strip_frame(data: bytes) -> bytes | None:
    """Return the payload of a Tuya UDP frame, or None if it is not one we understand."""
    if len(data) < 20:
        return None
    prefix = struct.unpack(">I", data[:4])[0]

    if prefix == PREFIX_55AA:
        # Header is 4 words; the length field counts the payload plus CRC and suffix.
        length = struct.unpack(">I", data[12:16])[0]
        payload = data[16:16 + max(length - 8, 0)]
        # Some frames carry a 4-byte return code ahead of the payload proper.
        for candidate in (payload, payload[4:]):
            if not candidate:
                continue
            if candidate.lstrip().startswith(b"{"):
                return candidate                # port 6666: already plaintext
            if len(candidate) % 16:
                continue                        # cannot be an AES-ECB block sequence
            try:                                # port 6667: AES-ECB, PKCS#7
                decryptor = Cipher(algorithms.AES(UDP_KEY), modes.ECB()).decryptor()
                clear = decryptor.update(candidate) + decryptor.finalize()
            except Exception:  # noqa: BLE001 - a malformed beacon must not kill the listener
                continue
            if clear and 0 < clear[-1] <= 16:
                clear = clear[:-clear[-1]]
            if clear.lstrip().startswith(b"{"):
                return clear
        return None

    if prefix == PREFIX_6699:
        length = struct.unpack(">I", data[14:18])[0]
        body = data[18:18 + length]
        if len(body) < 28:
            return None
        try:                                    # port 7000: AES-GCM, header is the AAD
            return AESGCM(UDP_KEY).decrypt(body[:12], body[12:], data[4:18])
        except Exception:  # noqa: BLE001
            return None

    return None


class _Beacons(asyncio.DatagramProtocol):
    """Collects beacons defensively; every field in one is attacker-controlled."""

    def __init__(self, found: dict[str, str], wanted: str | None = None) -> None:
        self._found = found
        self._wanted = wanted

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        payload = _strip_frame(data)
        if not payload:
            return
        try:
            info = json.loads(payload.decode("utf8", "ignore"))
        except ValueError:
            return
        if not isinstance(info, dict):
            return

        device_id = info.get("gwId") or info.get("devId")
        # Must be a string: it becomes a dict key, and a list or a number would raise.
        if not isinstance(device_id, str) or not device_id:
            return
        # When looking for one device, ignore the rest so a flood of forged ids for
        # other devices cannot crowd it out or fill memory.
        if self._wanted is not None and device_id != self._wanted:
            return
        if device_id not in self._found and len(self._found) >= MAX_BEACONS:
            return

        # Deliberately the sender's address, not the "ip" the packet claims. Trusting the
        # body would let anything on the network name any target - including a hostname,
        # which would be resolved and reached off the LAN entirely.
        self._found[device_id] = addr[0]

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Tuya discovery socket error: %s", exc)


async def discover(timeout: float = 20.0, wanted: str | None = None) -> dict[str, str]:
    """Listen on every beacon port and return {device_id: ip}.

    Ports already taken by another listener on the host are skipped rather than
    treated as fatal, so this still works alongside other Tuya integrations.
    """
    loop = asyncio.get_running_loop()
    found: dict[str, str] = {}
    transports = []
    opened: list[int] = []
    blocked: list[int] = []

    for port in PORTS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SO_REUSEADDR only. With SO_REUSEPORT the kernel load-balances arriving
        # datagrams between everyone bound to the port, so half the beacons would be
        # taken from any other Tuya integration on this host instead of shared with it.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", port))
        except OSError as err:
            # Another Tuya integration listening here is the usual reason.
            _LOGGER.debug("Tuya discovery: port %d unavailable (%s)", port, err)
            blocked.append(port)
            sock.close()
            continue
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Beacons(found, wanted), sock=sock)
        transports.append(transport)
        opened.append(port)

    if not transports:
        _LOGGER.warning(
            "Tuya discovery: could not open any beacon port (%s). Another Tuya "
            "integration is probably already listening; the address must be entered by hand",
            ", ".join(str(p) for p in blocked) or "none tried",
        )
        return found

    _LOGGER.debug("Tuya discovery listening %.0fs on %s%s", timeout,
                  ", ".join(str(p) for p in opened),
                  f" (blocked: {', '.join(str(p) for p in blocked)})" if blocked else "")

    try:
        await asyncio.sleep(timeout)
    finally:
        for transport in transports:
            transport.close()

    if found:
        _LOGGER.debug("Tuya discovery saw %d device(s)", len(found))
    else:
        _LOGGER.warning(
            "Tuya discovery heard nothing in %.0fs on port(s) %s. Either the spa is on a "
            "different network segment, or another integration is consuming the beacons",
            timeout, ", ".join(str(p) for p in opened),
        )
    return found


async def find_host(hass: HomeAssistant, device_id: str, timeout: float = 20.0) -> str | None:
    """Return the LAN address of one device, or None if it could not be found.

    Asks before listening. Devices on protocol 3.4 and 3.5 - which is what these spas
    are - stay silent until they receive a discovery request, so passive listening alone
    finds nothing. The passive sweep is kept as a fallback for older firmware that does
    announce itself unprompted.
    """
    try:
        answer = await hass.async_add_executor_job(_probe, device_id)
    except Exception as err:  # noqa: BLE001 - a failed probe is not fatal
        _LOGGER.debug("Active discovery probe failed: %s", err)
    else:
        if answer:
            _LOGGER.debug("Active discovery found %s at %s", device_id, answer)
            return answer

    _LOGGER.debug("No answer to the discovery request; listening for beacons instead")
    return (await discover(timeout, wanted=device_id)).get(device_id)


def _probe(device_id: str) -> str | None:
    """Broadcast a discovery request and return the address that answers."""
    found = tinytuya.find_device(dev_id=device_id)
    if isinstance(found, dict):
        # tinytuya reports a miss as {"ip": None, ...} rather than an empty result.
        return _as_address(found.get("ip"))
    return None


def _as_address(value: Any) -> str | None:
    """Accept only a literal IP address. A hostname here would be resolved and reached."""
    if not isinstance(value, str) or not value:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        _LOGGER.debug("Ignoring a discovery answer that is not an IP address: %r", value)
        return None
    return value
