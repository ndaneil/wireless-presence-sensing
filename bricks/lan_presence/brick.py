"""App-managed polling brick. Callbacks run on its loop thread."""
import copy
import logging
import threading

from arduino.app_utils import brick
from .client import PresenceClient, PresenceError


@brick
class LanPresence:
    def __init__(self, socket_path=None, on_update=None):
        self.client = PresenceClient(socket_path)
        self.on_update = on_update
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._snapshot = None
        self._error = None

    def start(self):
        self._stop.clear()

    def stop(self):
        self._stop.set()

    def snapshot(self):
        """Fetch a fresh snapshot. Raises PresenceError if unavailable."""
        return self.client.snapshot()

    def latest(self):
        """Return the latest poll, or None during startup/service failure."""
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def loop(self):
        try:
            current = self.client.snapshot()
            error = None
        except PresenceError as exc:
            current, error = None, str(exc)
        with self._lock:
            self._snapshot = current
        if error != self._error:
            logging.getLogger(__name__).warning(error or 'Presence service recovered')
            self._error = error
        if self.on_update:
            try:
                self.on_update(copy.deepcopy(current))
            except Exception:
                logging.getLogger(__name__).exception('Presence consumer failed')
        self._stop.wait(1)
