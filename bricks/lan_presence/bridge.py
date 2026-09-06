"""Bounded, cached Bridge reads. No database access on the RPC thread."""
import time

STATE_CODES = {'UNKNOWN': 0, 'AWAY': 1, 'HOME': 2}


class PresenceBridge:
    def __init__(self, latest, max_age=10):
        self.latest = latest
        self.max_age = max_age

    def _current(self):
        current = self.latest()
        if current is None or not 0 <= time.time() - current['generated_at'] <= self.max_age:
            return None
        return current

    def home_state(self):
        current = self._current()
        return current['state_code'] if current else 0

    def people_home(self):
        current = self._current()
        return current['people_home'] if current else 0

    def _field(self, collection, identifier, field, default):
        current = self._current()
        if current:
            for item in current[collection]:
                if item['id'] == identifier:
                    return item.get(field, default)
        return default

    def person_state(self, person_id):
        return STATE_CODES[self._field('people', person_id, 'state', 'UNKNOWN')]

    def device_state(self, device_id):
        return STATE_CODES[self._field('devices', device_id, 'state', 'UNKNOWN')]

    def person_last_seen(self, person_id):
        return int(self._field('people', person_id, 'last_seen', None) or 0)

    def device_last_seen(self, device_id):
        return int(self._field('devices', device_id, 'last_seen', None) or 0)

    def device_mac(self, device_id):
        return self._field('devices', device_id, 'mac', '')

    def register(self, bridge):
        for name in ('home_state', 'people_home', 'person_state', 'device_state',
                     'person_last_seen', 'device_last_seen', 'device_mac'):
            bridge.provide('presence_' + name, getattr(self, name))
