import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bricks/lan_presence/service"))

"""Dependency-free checks: python3 -m unittest discover -s tests -p test_core.py."""
import asyncio
import ast
import ipaddress
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Settings
from app.database.db import Database
from app.discovery.linux import LinuxDiscovery, Observation, parse_neighbours
from app.presence.engine import evaluate


class CoreTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for root in ('bricks', 'python', 'tests'):
            for path in Path(root).rglob('*.py'):
                ast.parse(path.read_text(), filename=str(path))

    def test_stale_and_reachable_evidence(self):
        rows = [{'dst': '192.168.1.2', 'lladdr': '02:00:00:00:00:01', 'state': ['STALE']},
                {'dst': '192.168.1.3', 'lladdr': '02:00:00:00:00:02', 'state': ['REACHABLE']},
                {'dst': '10.0.0.2', 'lladdr': '02:00:00:00:00:03', 'state': ['REACHABLE']}]
        networks = [ipaddress.ip_network('192.168.1.0/24')]
        result = parse_neighbours(rows, networks, set(), set())
        self.assertEqual([r.confirmed for r in result], [False, True])
        self.assertTrue(parse_neighbours(rows[:1], networks, set(), {'192.168.1.2'})[0].confirmed)
        self.assertEqual(parse_neighbours(rows[:1], networks, {ipaddress.ip_address('192.168.1.2')}, set()), [])

    def test_presence_boundaries(self):
        devices = [{'id': 1, 'person_id': 1, 'presence_enabled': True, 'last_seen': 1000, 'away_timeout_seconds': 1800}]
        people = [{'id': 1, 'name': 'Alex'}]
        for now, healthy, expected in [(1100, True, 'HOME'), (1300, True, 'UNKNOWN'), (2800, True, 'AWAY'), (2800, False, 'UNKNOWN')]:
            self.assertEqual(evaluate(devices, people, now, healthy)['state'], expected)
        devices.append({**devices[0], 'id': 2, 'last_seen': 2750})
        self.assertEqual(evaluate(devices, people, 2800, True)['state'], 'HOME')
        self.assertEqual(evaluate([], people, 2800, True)['state'], 'UNKNOWN')
        devices[0]['last_seen'] = None
        self.assertEqual(evaluate(devices[:1], people, 2800, True)['state'], 'UNKNOWN')

    def test_sqlite_preserves_confirmation_and_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'test.db'))
            try:
                db.observe([Observation('02:00:00:00:00:01', '192.0.2.2', 'ping', True)], 100)
                with db.connection as conn:
                    conn.execute("UPDATE devices SET friendly_name='Phone'")
                db.observe([Observation('02:00:00:00:00:01', '192.0.2.3', 'neighbour', False)], 200)
                device = db.devices()[0]
                self.assertEqual(device['last_seen'], 100)
                self.assertEqual(device['friendly_name'], 'Phone')
                self.assertEqual(device['current_ip'], '192.0.2.3')
                self.assertEqual(len(db.rows('SELECT * FROM observations')), 1)
                db.record_state({'state': 'UNKNOWN', 'reason': 'test'}, 200)
                db.record_state({'state': 'UNKNOWN', 'reason': 'test'}, 300)
                self.assertEqual(len(db.rows('SELECT * FROM home_state')), 1)
            finally:
                db.connection.close()

    def test_scan_uses_connected_subnet_and_interface(self):
        calls = []
        async def fake_command(*args, **kwargs):
            calls.append(args)
            if 'addr' in args:
                return 0, '[{"flags":["UP"],"addr_info":[{"local":"192.0.2.1","prefixlen":30,"scope":"global"}]}]'
            if args[0] == 'ping':
                return 0, ''
            if 'neigh' in args:
                return 0, '[{"dst":"192.0.2.2","lladdr":"02:00:00:00:00:01","state":["STALE"]}]'
            raise AssertionError(f'Unexpected command: {args}')
        with patch('app.discovery.linux.command', fake_command), patch('app.discovery.linux.discover_names', side_effect=OSError('Multicast unavailable')):
            provider = LinuxDiscovery(Settings())
            result = asyncio.run(provider.scan())
        self.assertTrue(result[0].confirmed)
        self.assertEqual([call for call in calls if call[0] == 'ping'], [('ping', '-n', '-I', 'wlan0', '-c', '1', '-W', '1', '192.0.2.2')])
        self.assertTrue(provider.warnings)
        calls.clear()
        with patch('app.discovery.linux.command', fake_command), patch('app.discovery.linux.discover_names') as mdns:
            provider = LinuxDiscovery(Settings(mdns=False))
            result = asyncio.run(provider.scan())
        self.assertTrue(result[0].confirmed)
        self.assertEqual(provider.warnings, [])
        mdns.assert_not_called()

    def test_large_subnet_refused_before_ping(self):
        async def fake_command(*args, **kwargs):
            self.assertEqual(args[0], 'ip')
            return 0, '[{"flags":["UP"],"addr_info":[{"local":"10.0.0.1","prefixlen":16,"scope":"global"}]}]'
        with patch('app.discovery.linux.command', fake_command):
            with self.assertRaisesRegex(RuntimeError, 'exceeds'):
                asyncio.run(LinuxDiscovery(Settings()).scan())


if __name__ == '__main__':
    unittest.main()
