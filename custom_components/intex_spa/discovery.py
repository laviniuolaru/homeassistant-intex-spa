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
import json
import logging
import socket
import struct
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_LOGGER = logging.getLogger(__name__)

# Not a secret: this key is compiled into every Tuya device and published widely.
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()

PORTS = (6666, 6667, 7000)
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
    def __init__(self, found: dict[str, str]) -> None:
        self._found = found

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        payload = _strip_frame(data)
        if not payload:
            return
        try:
            info: dict[str, Any] = json.loads(payload.decode("utf8", "ignore"))
        except ValueError:
            return
        device_id = info.get("gwId") or info.get("devId")
        if device_id:
            self._found[device_id] = info.get("ip") or addr[0]

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Tuya discovery socket error: %s", exc)


async def discover(timeout: float = 12.0) -> dict[str, str]:
    """Listen on every beacon port and return {device_id: ip}.

    Ports already taken by another listener on the host are skipped rather than
    treated as fatal, so this still works alongside other Tuya integrations.
    """
    loop = asyncio.get_running_loop()
    found: dict[str, str] = {}
    transports = []

    for port in PORTS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        try:
            sock.bind(("", port))
        except OSError as err:
            _LOGGER.debug("Tuya discovery: port %d unavailable (%s)", port, err)
            sock.close()
            continue
        transport, _ = await loop.create_datagram_endpoint(lambda: _Beacons(found), sock=sock)
        transports.append(transport)

    if not transports:
        _LOGGER.warning("Tuya discovery: none of the beacon ports could be opened")
        return found

    try:
        await asyncio.sleep(timeout)
    finally:
        for transport in transports:
            transport.close()

    _LOGGER.debug("Tuya discovery saw %d device(s)", len(found))
    return found


async def find_host(device_id: str, timeout: float = 12.0) -> str | None:
    """Return the LAN address of one device, or None if it stayed quiet."""
    return (await discover(timeout)).get(device_id)
