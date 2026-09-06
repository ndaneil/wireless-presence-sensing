import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY, mac TEXT NOT NULL UNIQUE,
                current_ip TEXT, hostname TEXT, friendly_name TEXT,
                first_seen REAL NOT NULL, last_seen REAL,
                presence_enabled INTEGER NOT NULL DEFAULT 0,
                person_id INTEGER REFERENCES people(id),
                away_timeout_seconds INTEGER NOT NULL DEFAULT 1800);
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, device_id INTEGER REFERENCES devices(id),
                timestamp REAL NOT NULL, ip TEXT, source TEXT);
            CREATE INDEX IF NOT EXISTS observations_time ON observations(timestamp);
            CREATE TABLE IF NOT EXISTS home_state (
                timestamp REAL NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL);
        ''')

    def rows(self, query, parameters=()):
        return [dict(row) for row in self.connection.execute(query, parameters)]

    def devices(self):
        return self.rows('SELECT * FROM devices ORDER BY coalesce(friendly_name, hostname, mac)')

    def people(self):
        return self.rows('SELECT * FROM people ORDER BY name')

    def observe(self, observations, now):
        with self.connection as conn:
            for item in observations:
                conn.execute('''INSERT INTO devices(mac, current_ip, hostname, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?) ON CONFLICT(mac) DO UPDATE SET
                    current_ip=excluded.current_ip, hostname=coalesce(excluded.hostname, devices.hostname),
                    last_seen=coalesce(excluded.last_seen, devices.last_seen)''',
                    (item.mac, item.ip, item.hostname, now, now if item.confirmed else None))
                if item.confirmed:
                    conn.execute('''INSERT INTO observations(device_id, timestamp, ip, source)
                        SELECT id, ?, ?, ? FROM devices WHERE mac=?''', (now, item.ip, item.source, item.mac))
            conn.execute('DELETE FROM observations WHERE timestamp < ?', (now - 30 * 86400,)) # Keeping only 30d of data for observations
            conn.execute('DELETE FROM home_state WHERE timestamp < ?', (now - 90 * 86400,)) # Keeping only 90d of data for state history

    def record_state(self, presence, now):
        previous = self.rows('SELECT state FROM home_state ORDER BY rowid DESC LIMIT 1')
        if not previous or previous[0]['state'] != presence['state']:
            with self.connection as conn:
                conn.execute('INSERT INTO home_state VALUES (?, ?, ?)', (now, presence['state'], presence['reason']))
