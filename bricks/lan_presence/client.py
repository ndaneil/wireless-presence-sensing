"""Synchronous data access for App Lab components using the shared Unix socket."""
import http.client
import json
import socket
from pathlib import Path


class PresenceError(RuntimeError):
    pass


class PresenceClient:
    def __init__(self, socket_path=None, timeout=3):
        root = Path(__file__).resolve().parents[2]
        self.socket_path = str(socket_path or root / 'data/lan-presence/presence.sock')
        self.timeout = timeout

    def _request(self, path, method='GET', body=None):
        connection = http.client.HTTPConnection('localhost', timeout=self.timeout)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(self.timeout)
        try:
            connection.sock.connect(self.socket_path)
            payload = None if body is None else json.dumps(body)
            connection.request(method, path, body=payload, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = json.loads(response.read())
            if response.status >= 400:
                raise PresenceError(f"HTTP {response.status}: {data.get('detail', data)}")
            return data
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise PresenceError(f'Presence service unavailable: {exc}') from exc
        finally:
            connection.close()

    def snapshot(self):
        result = self._request('/api/snapshot')
        if result.get('schema_version') != 1:
            raise PresenceError('Unsupported presence schema version')
        return result

    def devices(self):
        return self._request('/api/devices')

    def device(self, device_id):
        return self._request(f'/api/devices/{int(device_id)}')

    def people(self):
        return self._request('/api/people')

    def person(self, person_id):
        return self._request(f'/api/people/{int(person_id)}')

    def update_device(self, device_id, **changes):
        return self._request(f'/api/devices/{int(device_id)}', 'PATCH', changes)

    def create_person(self, name):
        return self._request('/api/people', 'POST', {'name': name})
