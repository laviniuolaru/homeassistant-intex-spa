"""Async, dependency-free client for the Intex Link (Tuya OEM) mobile API.

Used only to look up the device id and local key. Once those are known, all control
happens on the LAN; the cloud is contacted again only when the local key stops
working, which is what a re-pairing in the Intex Link app causes.

The request signing, AES-GCM envelope and two-step RSA login are adapted from
bpietroiu/homeassistant-intex-pool (MIT).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .const import APP_KEY, APP_VERSION, BASE_URL, CH_KEY, SECRET, TTID

_LOGGER = logging.getLogger(__name__)

# Only these keys take part in the signature, and only when non-empty.
SIGN_KEYS = frozenset({
    "a", "v", "lat", "lon", "lang", "deviceId", "appVersion", "ttid", "h5", "h5Token",
    "os", "clientId", "postData", "time", "requestId", "et", "n4h5", "sid", "chKey", "sp",
})


class IntexCloudError(Exception):
    """Transport or server-side error; retrying later may succeed."""


class IntexAuthError(IntexCloudError):
    """Credentials were rejected. Retrying will not help."""


def _swap(md5hex: str) -> str:
    """Tuya's byte-group shuffle applied to the postData digest before signing."""
    return md5hex[8:16] + md5hex[0:8] + md5hex[24:32] + md5hex[16:24]


def _sign(params: dict[str, str]) -> str:
    parts = [
        f"{k}={_swap(hashlib.md5(params[k].encode()).hexdigest()) if k == 'postData' else params[k]}"
        for k in sorted(params)
        if k in SIGN_KEYS and params.get(k)
    ]
    return hmac.new(SECRET.encode(), "||".join(parts).encode(), hashlib.sha256).hexdigest()


def _envelope_key(request_id: str, ecode: str | None) -> bytes:
    msg = SECRET + (f"_{ecode}" if ecode else "")
    return hmac.new(request_id.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16].encode()


def password_digest(password: str) -> str:
    """Hash a password the way the login expects.

    The API never sees the password itself, only this digest, so nothing else has to be
    kept. Call this once while the user is typing and store only the result.
    """
    return hashlib.md5(password.encode()).hexdigest()


def new_client_id() -> str:
    """A stable per-installation pseudo-device id, as the app would generate."""
    return (uuid.uuid4().hex + uuid.uuid4().hex)[:44]


class IntexCloud:
    """Minimal client: log in, list devices, read their local keys."""

    def __init__(self, session: aiohttp.ClientSession, client_id: str) -> None:
        self._session = session
        self._client_id = client_id
        self._sid: str = ""
        self._ecode: str = ""

    async def _call(self, action: str, version: str, post: dict | None = None) -> dict:
        request_id = str(uuid.uuid4())
        params: dict[str, str] = {
            "a": action,
            "v": version,
            "appVersion": APP_VERSION,
            "os": "Android",
            "lang": "en_US",
            "clientId": APP_KEY,
            "ttid": TTID,
            "deviceId": self._client_id,
            "chKey": CH_KEY,
            "et": "3",
            "time": str(int(time.time())),
            "requestId": request_id,
        }
        if self._sid:
            params["sid"] = self._sid
        key = _envelope_key(request_id, self._ecode if self._sid else None)
        if post is not None:
            nonce = os.urandom(12)
            blob = AESGCM(key).encrypt(nonce, json.dumps(post, separators=(",", ":")).encode(), None)
            params["postData"] = base64.b64encode(nonce + blob).decode()
        params["sign"] = _sign(params)

        try:
            async with self._session.post(f"{BASE_URL}/api.json", data=params) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise IntexCloudError(f"cannot reach the Intex cloud: {err}") from err
        except ValueError as err:
            raise IntexCloudError("the Intex cloud returned a malformed response") from err

        if isinstance(body.get("result"), str):
            blob = base64.b64decode(body["result"])
            body["result"] = json.loads(AESGCM(key).decrypt(blob[:12], blob[12:], None).decode())
        return body

    @staticmethod
    def _unwrap(body: dict):
        result = body.get("result")
        if not isinstance(result, dict):
            return result
        if result.get("success") is False:
            code = str(result.get("errorCode") or "").upper()
            message = str(result.get("errorMsg") or code or "unknown error")
            blob = f"{code} {message}".upper()
            # Rate limiting is transient. Anything credential-shaped is not.
            if any(w in blob for w in ("FREQUENT", "FREQUENCY", "LIMIT", "BUSY", "TIMEOUT")):
                raise IntexCloudError(message)
            if any(w in blob for w in ("PASSWD", "PASSWORD", "ACCOUNT", "USER_NOT", "USERNAME")):
                raise IntexAuthError(message)
            # Unknown failures are treated as transient: forcing the re-auth dialog on a
            # server hiccup is worse than retrying.
            raise IntexCloudError(message)
        return result.get("result", result)

    async def login(self, email: str, password_md5: str, country_code: str) -> None:
        """Two-step RSA login: fetch a token plus public key, then send the encrypted digest.

        Takes the digest, not the password: the caller hashes once at setup so the
        plaintext never has to be written to disk.
        """
        token = self._unwrap(await self._call(
            "smartlife.m.user.username.token.get", "2.0",
            post={"countryCode": country_code, "isUid": False, "username": email},
        ))
        public_key = rsa.RSAPublicNumbers(int(token["exponent"]), int(token["publicKey"])).public_key()
        encrypted = public_key.encrypt(password_md5.encode(), padding.PKCS1v15()).hex()

        session = self._unwrap(await self._call(
            "smartlife.m.user.email.password.login", "3.0",
            post={
                "countryCode": country_code,
                "email": email,
                "ifencrypt": 1,
                "options": '{"group": 1,"mfaCode": ""}',
                "passwd": encrypted,
                "token": token["token"],
            },
        ))
        self._sid = session["sid"]
        self._ecode = session["ecode"]

    async def _homes(self) -> list[dict]:
        return self._unwrap(await self._call("tuya.m.location.list", "1.0")) or []

    async def devices(self) -> list[dict]:
        """Every device on the account, across all homes, with its local key."""
        found: dict[str, dict] = {}
        for home in await self._homes():
            rows = self._unwrap(await self._call(
                "m.life.my.group.device.list", "2.2", post={"gid": home["groupId"]},
            )) or []
            for row in rows:
                device_id = row.get("devId")
                local_key = row.get("localKey")
                if not device_id or not local_key:
                    continue
                found[device_id] = {
                    "device_id": device_id,
                    "local_key": local_key,
                    "name": row.get("name") or "Intex Spa",
                    "product_id": row.get("productId") or "",
                    "online": bool(row.get("isOnline")),
                }
        _LOGGER.debug("Intex cloud returned %d device(s)", len(found))
        return list(found.values())

    async def local_key_for(self, device_id: str) -> str | None:
        """Re-read one device's local key. Used to recover after a re-pairing."""
        for device in await self.devices():
            if device["device_id"] == device_id:
                return device["local_key"]
        return None
