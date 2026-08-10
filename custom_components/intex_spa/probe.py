"""Work out which Tuya protocol version a spa speaks.

Getting this wrong is not a degraded experience, it is a dead integration: the wrong
version fails the session-key handshake, tinytuya reports 914, and every layer above
reads that as a rotated key. So it is settled once, by asking, rather than assumed.

Each attempt gets its own device object. Reusing one across versions leaves the failed
handshake's state behind and makes the next attempt fail for the wrong reason.
"""

from __future__ import annotations

import logging
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)

# Ordered by how likely they are on these spas: everything seen so far is 3.5, and the
# older pair are there for modules that predate it.
PROTOCOL_VERSIONS: tuple[str, ...] = ("3.5", "3.4", "3.3", "3.1")

PROBE_TIMEOUT = 5.0


def probe_protocol(device_id: str, host: str, local_key: str) -> tuple[str, dict[str, Any]] | None:
    """Return the first version that answers, with what it answered, or None."""
    for version in PROTOCOL_VERSIONS:
        device = tinytuya.Device(dev_id=device_id, address=host, local_key=local_key)
        try:
            device.set_version(float(version))
            device.set_socketTimeout(PROBE_TIMEOUT)
            device.set_socketRetryLimit(1)
            device.set_socketRetryDelay(0)
            status = device.status() or {}
            dps = status.get("dps")
            if isinstance(dps, dict) and dps:
                _LOGGER.debug("Spa answered on protocol %s with %d data points", version, len(dps))
                return version, dps
            _LOGGER.debug("Protocol %s rejected: %s", version, status.get("Error") or status)
        except Exception as err:  # noqa: BLE001 - any failure just means "not this one"
            _LOGGER.debug("Protocol %s failed: %s", version, err)
        finally:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass
    return None
