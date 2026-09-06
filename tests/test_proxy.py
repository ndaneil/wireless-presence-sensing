import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from web import create_proxy


class ProxyTests(unittest.TestCase):
    def test_preserves_request_and_backend_errors(self):
        received = []
        def backend(request):
            received.append(request)
            return httpx.Response(422, json={'detail': 'Assign a person'})
        with patch('web.httpx.AsyncHTTPTransport', return_value=httpx.MockTransport(backend)):
            with TestClient(create_proxy('/tmp/unused.sock')) as client:
                response = client.patch('/api/devices/1?check=yes', json={'presence_enabled': True},
                                        headers={'Origin': 'http://testserver'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail'], 'Assign a person')
        self.assertEqual(received[0].headers['host'], 'testserver')
        self.assertEqual(received[0].headers['origin'], 'http://testserver')
        self.assertEqual(received[0].url.query, b'check=yes')

    def test_backend_unavailable(self):
        def backend(request):
            raise httpx.ConnectError('offline')
        with patch('web.httpx.AsyncHTTPTransport', return_value=httpx.MockTransport(backend)):
            with TestClient(create_proxy('/tmp/unused.sock')) as client:
                response = client.get('/api/snapshot')
        self.assertEqual(response.status_code, 503)
