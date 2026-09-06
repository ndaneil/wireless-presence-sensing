"""Serve the brick's existing dashboard and API through App Lab port 8000."""
from contextlib import asynccontextmanager
import threading
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}


def create_proxy(socket_path):
    @asynccontextmanager
    async def lifespan(app):
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost', timeout=120) as client:
            app.state.client = client
            yield

    proxy = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @proxy.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS'])
    async def forward(path: str, request: Request):
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
        # Preserve Host/Origin for the backend's same-origin write checks.
        headers['accept-encoding'] = 'identity'
        try:
            response = await request.app.state.client.request(
                request.method, '/' + path, params=request.query_params,
                headers=headers, content=await request.body())
        except httpx.HTTPError:
            return JSONResponse({'detail': 'Presence service unavailable'}, status_code=503)
        return Response(response.content, status_code=response.status_code,
                        headers={k: v for k, v in response.headers.items()
                                 if k.lower() not in HOP_HEADERS | {'content-encoding'}})

    return proxy


class WebServer:
    def __init__(self, socket_path):
        self.server = uvicorn.Server(uvicorn.Config(create_proxy(socket_path), host='0.0.0.0', port=8000, log_level='info'))
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.server.run, name='presence-web', daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            self.stop()
            raise RuntimeError('Presence web server failed to start')

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def stop(self):
        self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
