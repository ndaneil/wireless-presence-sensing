# Presence data API description

`GET /api/snapshot` and `PresenceClient.snapshot()` return the same JSON-compatible
object. Times are Unix UTC seconds; ages are seconds at `generated_at`. Missing
last-seen timestamps/ages are `null`, not zero. A snapshot is computed on request,
so presence ages even when the device inventory has not changed.

Field | Type | Description
--- | --- | ---
`schema_version` | integer | `1`; consumers should reject unsupported versions
`generated_at` | number | Snapshot calculation time
`state` | string | `HOME`, `AWAY`, or `UNKNOWN`
`state_code` | integer | UNKNOWN=0, AWAY=1, HOME=2
`healthy` | boolean | A recent successful scan exists and the latest scan did not fail
`reason` | string | Human-readable household-state explanation
`people_home` | integer | Number of people whose state is HOME
`devices` | array | Device records described below
`people` | array | Resident records described below
`scan` | object | running, last_success, error, warnings, networks, interface, demo

## Devices

Every device includes `id`, `mac`, `current_ip`, `hostname`, `friendly_name`,
`first_seen`, `last_seen`, `person_id`, `presence_enabled`, `away_timeout_seconds`,
`state`, and `last_seen_age_seconds`. Names, owner and last seen can be null.
MAC is the stable inventory key within this database; IP may change. A phone
changing its private MAC creates another device record.

Device `state` describes its evidence even if `presence_enabled` is false.
Only enabled devices assigned to a person contribute to that person's presence.
`first_seen` means first inventory observation and may come from a stale neighbour
record. `last_seen` means latest positive reachability confirmation.

## People / users

Every person includes `id`, `name`, `state`, `tracked_devices` (count),
`device_ids` (all assigned devices), `tracked_device_ids`, `last_seen`, and
`last_seen_age_seconds`. A person's `last_seen` is the latest confirmation among
currently selected devices, so an untracked device cannot refresh their presence.
It is null if no selected device has ever been confirmed. Historical timestamps
are retained when a scan fails, while state becomes UNKNOWN.

`GET /api/people/{id}` also embeds the person's complete `devices` records.
Person IDs represent residents/owners and are not authentication identities.

## HTTP

All paths are relative to `http://UNO_Q_IP:8000` in the supplied App Lab app.

Method | Path | Result
--- | --- | ---
GET | `/api/snapshot` | Full versioned snapshot
GET | `/api/devices` | Device list with state and age
GET | `/api/devices/{id}` | One device; 404 if absent
PATCH | `/api/devices/{id}` | Edit identity/tracking; returns stored device fields
GET | `/api/people` | People with state, linked IDs and last seen
GET | `/api/people/{id}` | One person plus embedded devices; 404 if absent
POST | `/api/people` | Create with `{"name":"Daniel"}`; 409 for duplicate name
GET | `/api/presence` | Legacy household summary and device-id-to-state map
POST | `/api/scan` | Wait for scan; 409 if busy, 503 on failure
GET | `/docs` | FastAPI interactive API documentation

PATCH accepts only `friendly_name`, `person_id`, `presence_enabled`, and
`away_timeout_seconds` (60–86400). A selected device must have a person.
Browser cross-origin writes are rejected. There is no login or CORS allowance.
Read endpoints return UNKNOWN plus health information for scan failures; a
completely unavailable backend produces HTTP 503.

Example for another Linux component (Python standard library):

```python
import json
from urllib.request import urlopen

with urlopen('http://UNO_Q_IP:8000/api/snapshot', timeout=3) as response:
    current = json.load(response)
assert current['schema_version'] == 1
for device in current['devices']:
    print(device['mac'], device['current_ip'], device['last_seen'])
```

## In-app Python API

Import `PresenceClient` and `PresenceError` from `bricks.lan_presence`. The
constructor accepts `socket_path=None, timeout=3`; the default socket is
`<app root>/data/lan-presence/presence.sock`.

* `snapshot()` -- complete versioned object.
* `devices()` / `device(device_id)` -- device list or record.
* `people()` / `person(person_id)` -- people or one person with embedded devices.
* `create_person(name)` -- create a resident.
* `update_device(device_id, **changes)` -- edit assignments/tracking.

All are synchronous, bounded calls; failures raise `PresenceError`. Use the
managed `LanPresence` class's `on_update` callback or `latest()` for consumers
that should not block on HTTP. Do not share the SQLite connection with components.
External processes on the LAN use the HTTP interface instead of the Unix client.

## MCU Bridge

The example app registers these read-only handlers with `Bridge.provide`:

RPC name | Arguments | Return
--- | --- | ---
`presence_home_state` | none | State code
`presence_people_home` | none | Number of people HOME
`presence_person_state` | integer person ID | State code
`presence_device_state` | integer device ID | State code
`presence_person_last_seen` | integer person ID | Unix seconds, integer
`presence_device_last_seen` | integer device ID | Unix seconds, integer
`presence_device_mac` | integer device ID | MAC string

Bridge uses UNKNOWN=0, AWAY=1, HOME=2. Unknown IDs, service failure, or snapshots
older than ten seconds yield UNKNOWN/0/empty string. For last-seen RPCs, 0 means
unavailable or never confirmed. Full lists and long names stay on Python/HTTP;
scalar getters keep MCU RPC payloads bounded. Obtain persistent IDs from the
snapshot or dashboard API instead of relying on list position.

The example Python loop calls the sketch's `presence_display(state_code, people_home)` every two seconds, with a two-second timeout. The sketch watchdog switches to UNKNOWN after 15 seconds without an update. You can replace this handler with your own visualization; scanning and person assignments do not change.

To expose the getters in another App Lab app:

```python
from arduino.app_utils import App, Bridge
from bricks.lan_presence.brick import LanPresence
from bricks.lan_presence.bridge import PresenceBridge

presence = LanPresence()
PresenceBridge(presence.latest).register(Bridge)
App.run()
```

Use `Bridge.call` from the sketch to consume the provided RPCs, following your
installed Arduino_RouterBridge API. The included sketch demonstrates the opposite
direction (Python pushes the compact household summary) and requires no dynamic
JSON parser or full device inventory on the MCU.
