"""Arduino App Lab entry point. Container dependencies are provisioned on UNO Q."""
import logging
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arduino.app_utils import App, Bridge
from bricks.lan_presence.brick import LanPresence
from bricks.lan_presence.bridge import PresenceBridge
from web import WebServer

logging.basicConfig(level=logging.INFO)

presence = LanPresence()
rpc = PresenceBridge(presence.latest)
rpc.register(Bridge)
web = WebServer(presence.client.socket_path)
App.register(web)

led_enabled = os.getenv('PRESENCE_LED', '1') == '1'
last_led_error = None


def loop():
    global last_led_error
    if not web.alive():
        raise RuntimeError('Presence web server stopped unexpectedly')
    if led_enabled:
        try:
            Bridge.call('presence_display', rpc.home_state(), rpc.people_home(), timeout=2)
            last_led_error = None
        except Exception as exc:
            message = str(exc)
            if message != last_led_error:
                logging.warning('LED display unavailable: %s', message)
                last_led_error = message
    time.sleep(2)


App.run(user_loop=loop)
