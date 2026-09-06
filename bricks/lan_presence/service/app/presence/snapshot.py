"""Versioned JSON contract shared by HTTP, App Lab Python, and Bridge clients."""
from app.presence.engine import evaluate

SCHEMA_VERSION = 1
STATE_CODES = {'UNKNOWN': 0, 'AWAY': 1, 'HOME': 2}


def snapshot(devices, people, now, healthy, scan):
    result = evaluate(devices, people, now, healthy)
    enriched_devices = []
    for device in devices:
        last_seen = device['last_seen']
        enriched_devices.append({
            **device,
            'presence_enabled': bool(device['presence_enabled']),
            'state': result['devices'][device['id']],
            'last_seen_age_seconds': None if last_seen is None else max(0, now - last_seen),
        })
    enriched_people = []
    for person in result['people']:
        owned = [d for d in enriched_devices if d['person_id'] == person['id']]
        tracked = [d for d in owned if d['presence_enabled']]
        # A printer assigned to a person must not refresh that person's last_seen.
        last_seen = max((d['last_seen'] for d in tracked if d['last_seen'] is not None), default=None)
        enriched_people.append({
            **person,
            'device_ids': [d['id'] for d in owned],
            'tracked_device_ids': [d['id'] for d in tracked],
            'last_seen': last_seen,
            'last_seen_age_seconds': None if last_seen is None else max(0, now - last_seen),
        })
    return {
        'schema_version': SCHEMA_VERSION,
        'generated_at': now,
        'state': result['state'],
        'state_code': STATE_CODES[result['state']],
        'reason': result['reason'],
        'healthy': healthy,
        'people_home': sum(p['state'] == 'HOME' for p in enriched_people),
        'devices': enriched_devices,
        'people': enriched_people,
        'scan': scan,
    }
