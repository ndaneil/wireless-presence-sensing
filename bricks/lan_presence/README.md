# LAN Presence custom brick

Discovers the UNO Q's IPv4 LAN devices, persists their identities and person
assignments, and exposes a versioned presence snapshot. The container has host
network access; Python components communicate over a shared Unix socket.

Add `local:lan_presence: {}` to your app's `bricks` list and copy this entire
`lan_presence` directory into that app's `bricks` directory. Keep the directory name
so the default client socket path matches. App Lab builds the Docker service on
the UNO Q. It persists data in `${APP_HOME}/data/lan-presence`.

The basic client uses only Python's standard library:

```python
from bricks.lan_presence import PresenceClient

presence = PresenceClient()
current = presence.snapshot()
print(current['state'], current['people_home'])
for person in current['people']:
    print(person['name'], person['state'], person['last_seen'])
```

For an App-managed polling component:

```python
from arduino.app_utils import App
from bricks.lan_presence.brick import LanPresence


def update(current):
    if current is None:
        print('Presence service unavailable')
    else:
        print(current['state'])


presence = LanPresence(on_update=update)
App.run()
```

Callbacks run once per second on the brick's loop thread. They should finish
quickly. One failed consumer callback is logged and does not stop discovery.
`latest()` returns a defensive copy or `None` during startup/service failure.
`snapshot()` asks the service for current data and raises `PresenceError` on failure.

HTTP exposure and MCU Bridge registration belong to the containing app, the
brick does not claim port 8000 or register global RPC names itself. The example
app in this repository supplies both. See [API.md](docs/API.md) for details.

Name discovery uses Python Zeroconf directly on the configured interface, with
`PRESENCE_MDNS=1` by default.
