import asyncio
import logging
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import Settings
from app.database.db import Database
from app.discovery.linux import DemoDiscovery, LinuxDiscovery
from app.presence.engine import evaluate
from app.presence.snapshot import snapshot


class DevicePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    friendly_name: str | None = Field(default=None, max_length=100)
    person_id: int | None = Field(default=None, gt=0)
    presence_enabled: bool | None = None
    away_timeout_seconds: int | None = Field(default=None, ge=60, le=86400)

    @model_validator(mode='after')
    def required_values(self):
        for key in ('presence_enabled', 'away_timeout_seconds'):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f'{key} cannot be null')
        return self


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


class Monitor:
    def __init__(self, settings, database, discovery):
        self.settings, self.db, self.discovery = settings, database, discovery
        self.lock = asyncio.Lock()
        self.last_success = None
        self.last_error = None

    def presence(self):
        now = time.time()
        healthy = self.last_success is not None and self.last_error is None and now - self.last_success <= self.settings.scan_interval * 2 + 30
        result = evaluate(self.db.devices(), self.db.people(), now, healthy)
        self.db.record_state(result, now)
        return result

    def snapshot(self):
        now = time.time()
        healthy = self.last_success is not None and self.last_error is None and now - self.last_success <= self.settings.scan_interval * 2 + 30
        result = snapshot(self.db.devices(), self.db.people(), now, healthy, self.status())
        self.db.record_state(result, now)
        return result

    def status(self):
        return {'running': self.lock.locked(), 'last_success': self.last_success,
                'error': self.last_error, 'warnings': self.discovery.warnings,
                'networks': self.discovery.networks, 'interface': self.settings.interface,
                'demo': self.settings.demo,
                'mdns_provider': 'demo' if self.settings.demo else ('python-zeroconf' if self.settings.mdns else 'disabled'),
                'service_revision': 'mdns-zeroconf-v1'}

    async def scan(self):
        async with self.lock:
            try:
                observations = await self.discovery.scan()
                now = time.time()
                self.db.observe(observations, now)
                self.last_success, self.last_error = now, None
            except Exception as exc:
                self.last_error = str(exc)
                logging.getLogger(__name__).exception('LAN scan failed')
            self.presence()
        return self.status()

    async def run(self):
        while True:
            await self.scan()
            await asyncio.sleep(self.settings.scan_interval)


def create_app(settings=None, discovery=None, background=True):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        database = Database(settings.database)
        provider = discovery or (DemoDiscovery() if settings.demo else LinuxDiscovery(settings))
        app.state.monitor = Monitor(settings, database, provider)
        task = asyncio.create_task(app.state.monitor.run()) if background else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            database.connection.close()

    app = FastAPI(title='UNO Q LAN Presence', lifespan=lifespan)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / 'web' / 'templates'))

    @app.middleware('http')
    async def same_origin_writes(request: Request, call_next):
        # No CORS allowance; reject browser cross-origin writes, including form posts.
        if request.method in {'POST', 'PATCH', 'DELETE', 'PUT'}:
            origin = request.headers.get('origin')
            if (origin and origin != str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site') == 'cross-site':
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Cross-origin writes are disabled'}, status_code=403)
        return await call_next(request)

    @app.get('/')
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name='index.html', context={'demo': settings.demo})

    @app.get('/api/devices')
    async def devices():
        return app.state.monitor.snapshot()['devices']

    @app.get('/api/people')
    async def people():
        return app.state.monitor.snapshot()['people']

    @app.get('/api/snapshot')
    async def get_snapshot():
        return app.state.monitor.snapshot()

    @app.get('/api/devices/{device_id}')
    async def get_device(device_id: int):
        for device in app.state.monitor.snapshot()['devices']:
            if device['id'] == device_id:
                return device
        raise HTTPException(404, 'Device not found')

    @app.get('/api/people/{person_id}')
    async def get_person(person_id: int):
        current = app.state.monitor.snapshot()
        for person in current['people']:
            if person['id'] == person_id:
                return {**person, 'devices': [d for d in current['devices'] if d['person_id'] == person_id]}
        raise HTTPException(404, 'Person not found')

    @app.post('/api/people', status_code=201)
    async def create_person(person: PersonCreate):
        db = app.state.monitor.db
        try:
            with db.connection as conn:
                cursor = conn.execute('INSERT INTO people(name) VALUES (?)', (person.name,))
            return {'id': cursor.lastrowid, 'name': person.name}
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'A person with that name already exists')

    @app.patch('/api/devices/{device_id}')
    async def update_device(device_id: int, patch: DevicePatch):
        db = app.state.monitor.db
        existing = db.rows('SELECT * FROM devices WHERE id=?', (device_id,))
        if not existing:
            raise HTTPException(404, 'Device not found')
        changes = patch.model_dump(exclude_unset=True)
        merged = {**existing[0], **changes}
        if merged['presence_enabled'] and merged['person_id'] is None:
            raise HTTPException(422, 'Assign a person before enabling presence')
        if changes:
            try:
                with db.connection as conn:
                    conn.execute('UPDATE devices SET ' + ', '.join(f'{key}=?' for key in changes) + ' WHERE id=?', (*changes.values(), device_id))
            except sqlite3.IntegrityError:
                raise HTTPException(422, 'Person does not exist')
        return db.rows('SELECT * FROM devices WHERE id=?', (device_id,))[0]

    @app.get('/api/presence')
    async def presence():
        return {**app.state.monitor.presence(), 'scan': app.state.monitor.status()}

    @app.post('/api/scan')
    async def scan():
        monitor = app.state.monitor
        if monitor.lock.locked():
            raise HTTPException(409, 'A scan is already running')
        result = await monitor.scan()
        if result['error']:
            raise HTTPException(503, result['error'])
        return result

    return app


app = create_app()
