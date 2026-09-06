import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database: str = 'data/presence.sqlite3'
    interface: str = 'wlan0'
    scan_interval: int = 60
    max_hosts: int = 1024
    concurrency: int = 32
    demo: bool = False
    mdns: bool = True

    @classmethod
    def from_env(cls):
        settings = cls(
            database=os.getenv('PRESENCE_DATABASE', cls.database),
            interface=os.getenv('PRESENCE_INTERFACE', cls.interface),
            scan_interval=int(os.getenv('PRESENCE_SCAN_INTERVAL', '60')),
            max_hosts=int(os.getenv('PRESENCE_MAX_HOSTS', '1024')),
            concurrency=int(os.getenv('PRESENCE_CONCURRENCY', '32')),
            demo=os.getenv('PRESENCE_DEMO', '0') == '1',
            mdns=os.getenv('PRESENCE_MDNS', '1') == '1',
        )
        if settings.scan_interval < 10 or not 1 <= settings.concurrency <= 64 or not 1 <= settings.max_hosts <= 4096:
            raise ValueError('Invalid scan interval, concurrency, or host limit')
        return settings
