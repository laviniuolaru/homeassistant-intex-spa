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

# tinytuya's socket timeout is not just a read deadline: it is also the TCP connect
# deadline and, on protocol 3.4/3.5, the deadline for each leg of the session-key
# handshake. Too tight and a slow WiFi link fails the handshake, which tinytuya reports
# as error 914 - indistinguishable from a rotated key, so the integration would answer
# congestion with a cloud sign-in and possibly a password prompt.
#
# So it is raised while connecting and while a command is in flight, and only lowered
# for the idle wait, where it sets how long a queued command sits before the loop comes
# round to it, and so the delay a button press feels.
CONNECT_TIMEOUT = 5.0
IDLE_TIMEOUT = 0.25
SOCKET_TIMEOUT = IDLE_TIMEOUT        # kept for callers that report the loop cadence
HEARTBEAT_INTERVAL = 10.0
RECONNECT_DELAY = 5.0
# The socket opens lazily inside the first receive(), not when the device is built, so
# this has to outlast a connect attempt plus the reconnect delay.
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
        self._lifecycle = threading.Lock()
        self._stop = threading.Event()
        self._rebuild = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        with self._lifecycle:
            # A thread that outlived a timed-out join is still holding the spa's only
            # connection. Clearing _stop here would un-stop it and leave two running.
            if self._thread is not None and self._thread.is_alive():
                _LOGGER.debug("The spa connection thread is already running")
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(self._stop,), name="intex_spa_link", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle:
            self._stop.set()
            thread = self._thread
        if thread is not None:
            # Long enough to outlast a connect attempt in progress. Abandoning the thread
            # early would leave it holding the spa's one permitted connection while a
            # replacement opens another.
            thread.join(timeout=JOIN_TIMEOUT)
            if thread.is_alive():
                _LOGGER.warning("The spa connection thread did not stop in time")
            else:
                with self._lifecycle:
                    if self._thread is thread:
                        self._thread = None
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
        """Run everything queued, reporting each failure through its own Future.

        Deliberately does not raise: a command can fail for reasons that say nothing
        about the transport, and dropping the connection over one would cost seconds.
        """
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
                if not self._connected:
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

    def _run(self, stop: threading.Event) -> None:
        device: Any = None
        settled = False
        last_beat = 0.0

        while not stop.is_set():
            # Honour a pending rebuild before deciding whether to connect, so a request
            # that arrives while disconnected does not cause a connect-then-discard.
            if self._rebuild.is_set():
                self._rebuild.clear()
                if device is not None:
                    self._close(device)
                    device = None

            if device is None:
                try:
                    device = self._build_device()
                    device.set_socketPersistent(True)
                    # tinytuya otherwise retries five times with an uninterruptible five
                    # second sleep between each, so a single call could block this thread
                    # for minutes and starve every queued command. The reconnect loop
                    # below is the retry policy; one underneath it is not wanted.
                    device.set_socketRetryLimit(1)
                    device.set_socketRetryDelay(0)
                    device.set_socketTimeout(CONNECT_TIMEOUT)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Could not open the connection to the spa: %s", err)
                    self._set_connected(False, str(err))
                    stop.wait(RECONNECT_DELAY)
                    continue
                settled = False
                last_beat = 0.0

            try:
                if self._queue.qsize() and settled:
                    # Give a command the generous deadline too: it may have to reopen a
                    # socket the spa closed while idle.
                    device.set_socketTimeout(CONNECT_TIMEOUT)
                    self._drain(device)
                    device.set_socketTimeout(IDLE_TIMEOUT)
                else:
                    self._drain(device)

                data = device.receive()
                if isinstance(data, dict):
                    dps = data.get("dps")
                    if isinstance(dps, dict) and dps:
                        if not settled:
                            # The handshake is behind us; shorten the wait so queued
                            # commands are picked up promptly from here on.
                            device.set_socketTimeout(IDLE_TIMEOUT)
                            settled = True
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
                settled = False
                stop.wait(RECONNECT_DELAY)

        if device is not None:
            self._close(device)
