"""Owns the spa's single local connection on a dedicated thread.

The spa accepts one local client at a time and tinytuya is synchronous and not
thread-safe, so exactly one thread touches the socket. It spends its life blocked in
`receive()`, which is what turns this from polling into push: the spa announces changes
as they happen, including changes made from the Intex Link app.

Commands are handed to that same thread through a queue and answered with a Future, so
a write can never interleave with a read on the wire.
"""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

# This is how long a queued command may wait before the loop comes round to it, so it is
# also the delay a user feels after pressing a button. Each expiry is one socket syscall
# that returns empty, so four a second costs nothing measurable.
SOCKET_TIMEOUT = 0.25
HEARTBEAT_INTERVAL = 10.0
RECONNECT_DELAY = 5.0
# tinytuya connects while the device object is built, using its own timeout.
JOIN_TIMEOUT = 15.0


class _Job:
    __slots__ = ("func", "future")

    def __init__(self, func: Callable[[Any], Any]) -> None:
        self.func = func
        self.future: concurrent.futures.Future = concurrent.futures.Future()


class SpaLink:
    """A persistent connection to one spa, driven by a background thread."""

    def __init__(
        self,
        build_device: Callable[[], Any],
        on_push: Callable[[dict[str, Any]], None],
        on_state: Callable[[bool, str], None],
    ) -> None:
        self._build_device = build_device
        self._on_push = on_push
        self._on_state = on_state
        self._queue: queue.Queue[_Job] = queue.Queue()
        self._stop = threading.Event()
        self._rebuild = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="intex_spa_link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            # Long enough to outlast a connect attempt in progress. Abandoning the thread
            # early would leave it holding the spa's one permitted connection while a
            # replacement opens another.
            thread.join(timeout=JOIN_TIMEOUT)
            if thread.is_alive():
                _LOGGER.warning("The spa connection thread did not stop in time")
        # Anything still queued will never run; fail it rather than leave awaiters hanging.
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            if not job.future.done():
                job.future.set_exception(ConnectionError("the connection was shut down"))

    @property
    def connected(self) -> bool:
        return self._connected

    def rebuild(self) -> None:
        """Ask the thread to drop the socket and reconnect, after a key or address change."""
        self._rebuild.set()

    # --- submitting work -----------------------------------------------------------

    def submit(self, func: Callable[[Any], Any]) -> concurrent.futures.Future:
        """Run `func(device)` on the socket thread and return a Future for its result."""
        job = _Job(func)
        if self._stop.is_set():
            # Nothing will ever run it; say so now rather than let the caller wait out
            # its whole timeout.
            job.future.set_exception(ConnectionError("the connection is shut down"))
            return job.future
        self._queue.put(job)
        return job.future

    # --- the thread ----------------------------------------------------------------

    def _set_connected(self, connected: bool, detail: str = "") -> None:
        if connected != self._connected:
            self._connected = connected
            self._on_state(connected, detail)

    def _drain(self, device: Any) -> None:
        """Run everything queued. Raises if the socket died, so the caller reconnects."""
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            # Claim the job atomically; a caller that timed out may have cancelled it
            # between the queue pop and here, and settling a cancelled Future raises.
            if not job.future.set_running_or_notify_cancel():
                continue
            try:
                job.future.set_result(job.func(device))
                self._set_connected(True)
            except Exception as err:  # noqa: BLE001 - reported through the Future
                # Report it and carry on. A command can fail for reasons that say
                # nothing about the transport, and dropping the connection over one
                # would cost seconds of downtime; if the socket really is dead, the
                # next receive() will say so.
                job.future.set_exception(err)

    def _close(self, device: Any) -> None:
        try:
            device.close()
        except Exception:  # noqa: BLE001 - closing a dead socket must never raise
            pass

    def _run(self) -> None:
        device: Any = None
        last_beat = 0.0

        while not self._stop.is_set():
            if device is None:
                try:
                    device = self._build_device()
                    device.set_socketPersistent(True)
                    device.set_socketTimeout(SOCKET_TIMEOUT)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Could not open the connection to the spa: %s", err)
                    self._set_connected(False, str(err))
                    self._stop.wait(RECONNECT_DELAY)
                    continue
                last_beat = 0.0

            if self._rebuild.is_set():
                self._rebuild.clear()
                self._close(device)
                device = None
                continue

            try:
                self._drain(device)

                data = device.receive()
                if isinstance(data, dict):
                    dps = data.get("dps")
                    if isinstance(dps, dict) and dps:
                        self._set_connected(True)
                        self._on_push(dps)
                    elif data.get("Err"):
                        raise ConnectionError(str(data.get("Error") or data["Err"]))

                now = time.monotonic()
                if now - last_beat >= HEARTBEAT_INTERVAL:
                    device.heartbeat(nowait=True)
                    last_beat = now
            except Exception as err:  # noqa: BLE001 - any failure means reconnect
                _LOGGER.debug("Spa connection lost, will reconnect: %s", err)
                self._set_connected(False, str(err))
                self._close(device)
                device = None
                self._stop.wait(RECONNECT_DELAY)

        if device is not None:
            self._close(device)
