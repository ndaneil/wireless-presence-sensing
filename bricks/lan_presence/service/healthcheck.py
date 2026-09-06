"""Container readiness checks for the API."""
import http.client
import socket

connection = http.client.HTTPConnection('localhost', timeout=2)
connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
connection.sock.settimeout(2)
try:
    connection.sock.connect('/data/presence.sock')
    connection.request('GET', '/api/snapshot')
    response = connection.getresponse()
    response.read()
    raise SystemExit(0 if response.status == 200 else 1)
finally:
    connection.close()
