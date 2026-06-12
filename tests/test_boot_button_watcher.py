"""
Unit tests for the ESP32 BOOT-button watcher lifecycle in displaywallet.py.

Targets the onResume re-attach fix: `_start_boot_button_watcher` must be
idempotent (calling it while a watcher is alive is a no-op) but must
restart the watcher when the previous task died — detected via the task
handle's done() and the `_boot_button_alive_ms` heartbeat the watcher
loop refreshes every iteration.

The method is exercised unbound against a stub object, with
displaywallet's TaskManager swapped for a recorder and a fake `machine`
module injected so the desktop build takes the real code path. The
desktop-without-machine no-op path is covered too.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_boot_button_watcher.py
"""

import sys
import time
import unittest

try:
    import displaywallet
    _HAVE_WATCHER = hasattr(displaywallet.DisplayWallet, "_start_boot_button_watcher")
except Exception:
    _HAVE_WATCHER = False


class _FakePin:
    IN = 1
    PULL_UP = 2

    def __init__(self, *args, **kwargs):
        pass

    def value(self):
        return 1  # released


class _FakeMachine:
    """Stand-in for the `machine` module — `from machine import Pin`
    resolves attributes off whatever object sits in sys.modules."""
    Pin = _FakePin


class _FakeTask:
    def __init__(self):
        self._done = False

    def done(self):
        return self._done


class _RecordingTaskManager:
    """Counts create_task calls and closes the coroutine immediately so
    the watcher loop never actually runs in the test process."""

    def __init__(self):
        self.created = 0

    def create_task(self, coro):
        self.created += 1
        try:
            coro.close()
        except Exception:
            pass
        return _FakeTask()


class _StubWallet:
    """Bare object for unbound method calls — the watcher methods set all
    the attributes they need on first use. Only the coroutine factory the
    starter passes to TaskManager.create_task has to exist up front."""

    async def _boot_button_watcher_task(self):
        pass  # never runs — the recording TaskManager closes the coroutine


@unittest.skipUnless(_HAVE_WATCHER, "BOOT-button watcher not installed")
class TestBootButtonWatcherLifecycle(unittest.TestCase):

    def setUp(self):
        self._orig_tm = displaywallet.TaskManager
        self._had_machine = "machine" in sys.modules
        self._orig_machine = sys.modules.get("machine")
        self.tm = _RecordingTaskManager()
        displaywallet.TaskManager = self.tm
        sys.modules["machine"] = _FakeMachine

    def tearDown(self):
        displaywallet.TaskManager = self._orig_tm
        if self._had_machine:
            sys.modules["machine"] = self._orig_machine
        else:
            del sys.modules["machine"]

    def _start(self, w):
        displaywallet.DisplayWallet._start_boot_button_watcher(w)

    def test_first_call_starts_the_watcher(self):
        w = _StubWallet()
        self._start(w)
        self.assertEqual(self.tm.created, 1)
        self.assertTrue(w._boot_button_keep_running)

    def test_idempotent_while_watcher_alive(self):
        # The fix calls _start_boot_button_watcher from onResume on every
        # foreground return — when the watcher is alive (task not done,
        # heartbeat fresh) that must be a no-op, otherwise two racing
        # watchers would each flip the wallet slot per press.
        w = _StubWallet()
        self._start(w)
        self._start(w)
        self._start(w)
        self.assertEqual(self.tm.created, 1)

    def test_restarts_when_task_done(self):
        w = _StubWallet()
        self._start(w)
        w._boot_button_task._done = True  # watcher task exited
        self._start(w)
        self.assertEqual(self.tm.created, 2)

    def test_restarts_when_heartbeat_stale(self):
        # task.done() can miss a wedged task — the heartbeat (refreshed by
        # the watcher loop every ~50 ms) is the canonical liveness signal.
        # 500 ms without a beat means the watcher silently died.
        w = _StubWallet()
        self._start(w)
        w._boot_button_alive_ms = time.ticks_add(time.ticks_ms(), -5000)
        self._start(w)
        self.assertEqual(self.tm.created, 2)
        # And the stale path must flag the old loop to exit before
        # starting the new one... which the restart then re-enables.
        self.assertTrue(w._boot_button_keep_running)

    def test_desktop_without_machine_is_noop(self):
        del sys.modules["machine"]  # simulate desktop build (no GPIO)
        try:
            w = _StubWallet()
            self._start(w)
            self.assertEqual(self.tm.created, 0)
            self.assertFalse(w._boot_button_keep_running)
        finally:
            sys.modules["machine"] = _FakeMachine  # restore for tearDown


if __name__ == "__main__":
    unittest.main()
