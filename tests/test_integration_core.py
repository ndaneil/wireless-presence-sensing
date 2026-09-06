"""Integration contracts checked without third-party packages or board access."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bricks/lan_presence/service'))
sys.path.insert(0, str(ROOT))
from app.presence.snapshot import snapshot
from bricks.lan_presence.bridge import PresenceBridge
from bricks.lan_presence.client import PresenceClient, PresenceError


def sample(now):
    devices = [dict(id=1, mac='02:00:00:00:00:01', current_ip='192.0.2.2',
                    hostname='phone.local', friendly_name='Phone', person_id=1,
                    presence_enabled=1, away_timeout_seconds=1800, first_seen=now - 1000,
                    last_seen=now - 100),
               dict(id=2, mac='02:00:00:00:00:02', current_ip='192.0.2.3',
                    hostname='printer.local', friendly_name=None, person_id=1,
                    presence_enabled=0, away_timeout_seconds=1800, first_seen=now - 1000,
                    last_seen=now)]
    return snapshot(devices, [{'id': 1, 'name': 'Alex'}], now, True, {})


class IntegrationCoreTests(unittest.TestCase):
    def test_snapshot_links_and_last_seen_semantics(self):
        result = sample(2000)
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['state_code'], 2)
        self.assertEqual(result['people_home'], 1)
        person = result['people'][0]
        self.assertEqual(person['device_ids'], [1, 2])
        self.assertEqual(person['tracked_device_ids'], [1])
        self.assertEqual(person['last_seen'], 1900)
        self.assertEqual(person['last_seen_age_seconds'], 100)
        self.assertIs(result['devices'][0]['presence_enabled'], True)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_unknown_retains_historical_information(self):
        data = sample(2000)
        result = snapshot(data['devices'], [{'id': 1, 'name': 'Alex'}], 3000, False, {'error': 'down'})
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['people_home'], 0)
        self.assertEqual(result['people'][0]['last_seen'], 1900)
        self.assertEqual(result['devices'][0]['mac'], '02:00:00:00:00:01')

    def test_bridge_registration_and_expiry(self):
        current = sample(time.time())
        adapter = PresenceBridge(lambda: current)
        handlers = {}
        adapter.register(types.SimpleNamespace(provide=lambda name, fn: handlers.update({name: fn})))
        self.assertEqual(handlers['presence_home_state'](), 2)
        self.assertEqual(handlers['presence_device_mac'](1), '02:00:00:00:00:01')
        self.assertEqual(handlers['presence_person_last_seen'](1), int(current['people'][0]['last_seen']))
        self.assertEqual(handlers['presence_person_state'](999), 0)
        current['generated_at'] -= 30
        self.assertEqual(adapter.home_state(), 0)
        self.assertEqual(adapter.people_home(), 0)
        self.assertEqual(adapter.device_mac(1), '')
        current = None
        self.assertEqual(adapter.person_last_seen(1), 0)

    def test_client_contract_and_rejects_unknown_schema(self):
        client = PresenceClient('/tmp/example.sock')
        with patch.object(client, '_request', return_value=sample(2000)) as request:
            self.assertEqual(client.snapshot()['schema_version'], 1)
            request.assert_called_once_with('/api/snapshot')
        with patch.object(client, '_request', return_value={'schema_version': 99}):
            with self.assertRaises(PresenceError):
                client.snapshot()
        with patch.object(client, '_request', return_value={}) as request:
            client.update_device(4, presence_enabled=True, person_id=2)
            request.assert_called_once_with('/api/devices/4', 'PATCH', {'presence_enabled': True, 'person_id': 2})

    def test_brick_clears_failed_cache_and_isolates_consumers(self):
        # Supply only the decorator. Arduino runtime itself is not installed here.
        fake_utils = types.ModuleType('arduino.app_utils')
        fake_utils.brick = lambda cls: cls
        spec = importlib.util.spec_from_file_location('bricks.lan_presence._test_brick', ROOT / 'bricks/lan_presence/brick.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'arduino': types.ModuleType('arduino'), 'arduino.app_utils': fake_utils}):
            spec.loader.exec_module(module)
        received = []
        brick = module.LanPresence(on_update=received.append)
        brick._stop.set()  # No sleep in the test.
        with patch.object(brick.client, 'snapshot', return_value=sample(time.time())):
            brick.loop()
        current = brick.latest()
        current['people'][0]['name'] = 'Changed'
        self.assertEqual(brick.latest()['people'][0]['name'], 'Alex')
        with patch.object(brick.client, 'snapshot', side_effect=PresenceError('offline')):
            with self.assertLogs('bricks.lan_presence._test_brick', level='WARNING'):
                brick.loop()
        self.assertIsNone(brick.latest())
        self.assertIsNone(received[-1])


if __name__ == '__main__':
    unittest.main()
