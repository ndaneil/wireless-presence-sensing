import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bricks/lan_presence/service"))

from fastapi.testclient import TestClient

from app.config import Settings
from app.discovery.linux import DemoDiscovery
from app.main import create_app


def test_api_workflow_and_persistence(tmp_path):
    settings = Settings(database=str(tmp_path / 'test.db'), demo=True)
    with TestClient(create_app(settings, background=False)) as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/presence').json()['state'] == 'UNKNOWN'
        assert client.post('/api/scan').status_code == 200
        device = client.get('/api/devices').json()[0]
        person = client.post('/api/people', json={'name': 'Alex'}).json()
        assert client.post('/api/people', json={'name': 'Alex'}).status_code == 409
        url = f"/api/devices/{device['id']}"
        assert client.patch(url, json={'presence_enabled': True}).status_code == 422
        assert client.patch(url, json={'person_id': 999}).status_code == 422
        assert client.patch(url, json={'away_timeout_seconds': None}).status_code == 422
        assert client.patch(url, json={'mac': 'bad'}).status_code == 422
        assert client.patch(url, json={'friendly_name': 'My phone', 'person_id': person['id'], 'presence_enabled': True}).status_code == 200
        assert client.get('/api/presence').json()['state'] == 'HOME'
        snapshot = client.get('/api/snapshot').json()
        assert snapshot['schema_version'] == 1
        assert snapshot['people'][0]['last_seen'] == device['last_seen']
        assert snapshot['people'][0]['device_ids'] == [device['id']]
        assert client.get(url).json()['mac'] == device['mac']
        detail = client.get(f"/api/people/{person['id']}").json()
        assert detail['devices'][0]['mac'] == device['mac']
        assert client.get('/api/people/999').status_code == 404
        assert client.get('/api/devices/999').status_code == 404
        assert client.post('/api/scan', headers={'Origin': 'https://example.com'}).status_code == 403
    with TestClient(create_app(settings, background=False)) as client:
        assert any(d['friendly_name'] == 'My phone' for d in client.get('/api/devices').json())
        assert client.get('/api/presence').json()['state'] == 'UNKNOWN'


def test_failed_scan_invalidates_presence(tmp_path):
    class Broken(DemoDiscovery):
        async def scan(self):
            raise RuntimeError('Interface down')
    with TestClient(create_app(Settings(database=str(tmp_path / 'test.db')), discovery=Broken(), background=False)) as client:
        assert client.post('/api/scan').status_code == 503
        result = client.get('/api/presence').json()
        assert result['state'] == 'UNKNOWN'
        assert result['scan']['error'] == 'Interface down'


class MonitorTests(unittest.TestCase):
    def test_api(self):
        with tempfile.TemporaryDirectory() as directory:
            test_api_workflow_and_persistence(Path(directory))

    def test_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertLogs('app.main', level='ERROR'):
                test_failed_scan_invalidates_presence(Path(directory))
