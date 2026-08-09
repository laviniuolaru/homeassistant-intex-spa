"""Exercise the socket thread with a fake device: no Home Assistant, no spa, no tinytuya."""
import pathlib
import sys
import threading
import time
from importlib import util

# Load by file path; going through the package would import Home Assistant.
_spec = util.spec_from_file_location(
    "link", pathlib.Path(__file__).resolve().parents[1] / "custom_components/intex_spa/link.py"
)
link_mod = util.module_from_spec(_spec)
_spec.loader.exec_module(link_mod)

link_mod.RECONNECT_DELAY = 0.05          # keep the tests quick
link_mod.CONNECT_TIMEOUT = 0.05
link_mod.IDLE_TIMEOUT = 0.05
link_mod.HEARTBEAT_INTERVAL = 0.2

results = []


def check(name, condition, detail=""):
    results.append(condition)
    print(f"  {'OK   ' if condition else 'FAIL '} {name}{'  ' + detail if detail else ''}")


class FakeDevice:
    """Hands out queued replies, then goes quiet. Records what was done to it."""

    def __init__(self, replies=None, fail_after=None):
        self.replies = list(replies or [])
        self.fail_after = fail_after
        self.receives = 0
        self.heartbeats = 0
        self.closed = False
        self.persistent = False
        self.timeout = None

    def set_socketPersistent(self, value):
        self.persistent = value

    def set_socketTimeout(self, value):
        self.timeout = value

    def set_socketRetryLimit(self, value):
        self.retry_limit = value

    def set_socketRetryDelay(self, value):
        self.retry_delay = value

    def receive(self):
        self.receives += 1
        if self.fail_after is not None and self.receives > self.fail_after:
            raise ConnectionError("socket died")
        if self.replies:
            return self.replies.pop(0)
        time.sleep(0.01)
        return None

    def heartbeat(self, nowait=True):
        self.heartbeats += 1

    def close(self):
        self.closed = True

    def status(self):
        return {"dps": {"110": 90}}


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# 1. pushes reach the callback without anyone polling
pushed = []
device = FakeDevice(replies=[{"dps": {"104": True}}, {"dps": {"110": 91}}])
sl = link_mod.SpaLink(lambda: device, pushed.append, lambda c, d: None)
sl.start()
check("pushed updates arrive on their own", wait_for(lambda: len(pushed) == 2), str(pushed))
check("the socket was made persistent", device.persistent is True)
check("tinytuya's own retry loop was disabled", getattr(device, "retry_limit", None) == 1)

# an error dict is how tinytuya really reports a closed socket or a bad key
errs = FakeDevice(replies=[{"dps": {"104": True}}, {"Err": "914", "Error": "decrypt failed"}])
seen = []
sl2 = link_mod.SpaLink(lambda: errs, lambda d: None, lambda c, d: seen.append((c, d)))
sl2.start()
check("an error reply is treated as a lost connection",
      wait_for(lambda: any(c is False for c, _ in seen)), str(seen))
sl2.stop()

# 2. submitted work runs on the socket thread, not the caller's
caller = threading.get_ident()
ran_on = sl.submit(lambda dev: threading.get_ident()).result(timeout=3)
check("work runs on the socket thread", ran_on != caller)

# 3. heartbeats keep the connection alive while nothing happens
check("heartbeats are sent while idle", wait_for(lambda: device.heartbeats >= 1),
      f"heartbeats={device.heartbeats}")

# 4. an exception inside a job reaches the caller instead of killing the thread
def boom(_dev):
    raise ValueError("no")


try:
    sl.submit(boom).result(timeout=3)
    check("a failing job propagates to the caller", False, "no exception raised")
except ValueError:
    check("a failing job propagates to the caller", True)
sl.stop()
check("the device was closed on stop", device.closed is True)

# 5. a dead socket reconnects by itself
built = []


def build_flaky():
    dev = FakeDevice(replies=[{"dps": {"104": True}}], fail_after=1)
    built.append(dev)
    return dev


states = []
sl = link_mod.SpaLink(build_flaky, lambda dps: None, lambda c, d: states.append(c))
sl.start()
check("it reconnects after the socket dies", wait_for(lambda: len(built) >= 2),
      f"devices built={len(built)}")
check("disconnection was reported", False in states, str(states))
sl.stop()

# 6. rebuild() forces a fresh connection
built.clear()
sl = link_mod.SpaLink(build_flaky, lambda dps: None, lambda c, d: None)
sl.start()
wait_for(lambda: len(built) >= 1)
before = len(built)
sl.rebuild()
check("rebuild opens a new connection", wait_for(lambda: len(built) > before),
      f"{before} -> {len(built)}")
sl.stop()

# 7. work queued after shutdown fails instead of hanging for ever
sl = link_mod.SpaLink(lambda: FakeDevice(), lambda dps: None, lambda c, d: None)
sl.start()
sl.stop()
future = sl.submit(lambda dev: "never")
sl.stop()
try:
    future.result(timeout=1)
    check("queued work after shutdown does not hang", False, "it returned a result")
except ConnectionError:
    check("queued work after shutdown does not hang", True)
except Exception as err:  # noqa: BLE001
    check("queued work after shutdown does not hang", False, type(err).__name__)

print("\n" + ("ALL PASSED" if all(results) else "THERE WERE FAILURES"))
sys.exit(0 if all(results) else 1)
