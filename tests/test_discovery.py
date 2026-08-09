"""Unit-test the beacon frame parser with synthetic packets for all three dialects."""
import asyncio
import json
import os
import struct
import types
import pathlib
import sys
from importlib import util

# discovery.py now reaches for tinytuya (active probe) and HomeAssistant typing; the
# frame parser under test needs neither, so they are stubbed out.
_tt = types.ModuleType("tinytuya")
_tt.find_device = lambda dev_id=None: None
sys.modules["tinytuya"] = _tt
_ha = types.ModuleType("homeassistant"); _ha.__path__ = []
sys.modules["homeassistant"] = _ha
_core = types.ModuleType("homeassistant.core"); _core.HomeAssistant = object
sys.modules["homeassistant.core"] = _core


from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

# Load the module straight from its file: importing it through the package would
# pull in Home Assistant, which is not available when running the tests standalone.
_spec = util.spec_from_file_location(
    "discovery",
    pathlib.Path(__file__).resolve().parents[1] / "custom_components/intex_spa/discovery.py",
)
discovery = util.module_from_spec(_spec)
_spec.loader.exec_module(discovery)

BEACON = {"ip": "192.168.1.133", "gwId": "bf6e232413d5826737m9jg", "version": "3.5"}
CLEAR = json.dumps(BEACON).encode()


def frame_55aa(payload: bytes) -> bytes:
    return (struct.pack(">IIII", 0x000055AA, 0, 0x13, len(payload) + 8)
            + payload + struct.pack(">II", 0, 0x0000AA55))


def pkcs7(data: bytes) -> bytes:
    pad = 16 - len(data) % 16
    return data + bytes([pad]) * pad


def build_6666() -> bytes:
    return frame_55aa(CLEAR)


def build_6667() -> bytes:
    enc = Cipher(algorithms.AES(discovery.UDP_KEY), modes.ECB()).encryptor()
    return frame_55aa(enc.update(pkcs7(CLEAR)) + enc.finalize())


def build_7000() -> bytes:
    nonce = os.urandom(12)
    header = struct.pack(">IHIII", 0x00006699, 0, 0, 0x13, len(CLEAR) + 28)
    blob = AESGCM(discovery.UDP_KEY).encrypt(nonce, CLEAR, header[4:18])
    return header + nonce + blob + struct.pack(">I", 0x00009966)


ok = True
for name, packet in (("6666 plaintext", build_6666()),
                     ("6667 AES-ECB", build_6667()),
                     ("7000 AES-GCM", build_7000())):
    out = discovery._strip_frame(packet)
    parsed = json.loads(out.decode()) if out else None
    good = parsed == BEACON
    ok &= good
    print(f"  {name:16s} {'OK' if good else 'FAIL'}  -> {parsed}")

print(f"  {'garbage':16s} {'OK' if discovery._strip_frame(b'nu e un cadru') is None else 'FAIL'}")
print(f"  {'too short':16s} {'OK' if discovery._strip_frame(b'\\x00\\x00U\\xaa') is None else 'FAIL'}")

# --- a beacon is unauthenticated, so none of its fields may be trusted ---
print("\nhostile beacons:")


def feed(payload, sender="192.168.1.50", wanted=None):
    found = {}
    proto = discovery._Beacons(found, wanted)
    proto.datagram_received(frame_55aa(json.dumps(payload).encode()), (sender, 6666))
    return found


ok = True
cases = [
    ("the claimed ip is ignored in favour of the sender",
     feed({"gwId": "dev1", "ip": "10.9.9.9"}) == {"dev1": "192.168.1.50"}),
    ("a hostname in the body cannot redirect us",
     feed({"gwId": "dev1", "ip": "attacker.example.com"}) == {"dev1": "192.168.1.50"}),
    ("a non-string device id is dropped, not used as a key",
     feed({"gwId": 1234}) == {}),
    ("an unhashable device id does not raise",
     feed({"gwId": {"a": 1}}) == {}),
    ("a bare json value is ignored",
     feed(12345) == {}),
    ("beacons for other devices are filtered out when looking for one",
     feed({"gwId": "other"}, wanted="dev1") == {}),
    ("the device being looked for is still accepted",
     feed({"gwId": "dev1"}, wanted="dev1") == {"dev1": "192.168.1.50"}),
]
for name, good in cases:
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'} {name}")

flood = {}
proto = discovery._Beacons(flood)
for i in range(discovery.MAX_BEACONS + 50):
    proto.datagram_received(frame_55aa(json.dumps({"gwId": f"d{i}"}).encode()), ("192.168.1.50", 6666))
capped = len(flood) <= discovery.MAX_BEACONS
ok &= capped
print(f"  {'OK  ' if capped else 'FAIL'} a flood cannot grow memory without bound  ({len(flood)} kept)")

print("\nlistening 8s for real beacons (none expected when run behind NAT)...")
found = asyncio.run(discovery.discover(timeout=8.0))
print("  found:", found or "none")
sys.exit(0 if ok else 1)
