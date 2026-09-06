"""Read only network configuration. Probes IPv4 peers without changing interfaces."""
import asyncio
import ipaddress
import json
import re
from dataclasses import dataclass

from app.discovery.mdns import discover_names


@dataclass
class Observation:
    mac: str
    ip: str
    source: str
    confirmed: bool
    hostname: str | None = None


async def command(*args, timeout=10, allowed=(0,)):
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode not in allowed:
        raise RuntimeError(f'{args[0]} failed: {stderr.decode().strip()}')
    return process.returncode, stdout.decode()


def parse_neighbours(rows, networks, own_ips, replies):
    observations = []
    for row in rows:
        mac = row.get('lladdr', '').lower()
        try:
            address = ipaddress.ip_address(row['dst'])
        except (KeyError, ValueError):
            continue
        if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac) or int(mac[:2], 16) & 1:
            continue
        if address in own_ips or not any(address in network for network in networks):
            continue
        states = row.get('state', [])
        confirmed = str(address) in replies or 'REACHABLE' in states
        observations.append(Observation(mac, str(address), 'ping' if str(address) in replies else 'neighbour', confirmed))
    return observations


class LinuxDiscovery:
    def __init__(self, settings):
        self.settings = settings
        self.networks = []
        self.warnings = []

    async def scan(self):
        self.warnings = []
        interface = self.settings.interface
        _, raw = await command('ip', '-j', '-4', 'addr', 'show', 'dev', interface)
        rows = json.loads(raw)
        if not rows or 'UP' not in rows[0].get('flags', []) or rows[0].get('operstate') == 'DOWN':
            raise RuntimeError(f'{interface} is unavailable or down')
        addresses = [ipaddress.ip_interface(f"{a['local']}/{a['prefixlen']}") for a in rows[0]['addr_info'] if a.get('scope') == 'global']
        if not addresses:
            raise RuntimeError(f'{interface} has no global IPv4 address')
        networks = list({a.network for a in addresses})
        self.networks = sorted(map(str, networks))
        if sum(n.num_addresses for n in networks) > self.settings.max_hosts + 2:
            raise RuntimeError('Connected subnet exceeds PRESENCE_MAX_HOSTS; scan refused')
        own_ips = {a.ip for a in addresses}
        hosts = {str(ip) for n in networks for ip in n.hosts() if ip not in own_ips}
        semaphore = asyncio.Semaphore(self.settings.concurrency)
        async def ping(host):
            async with semaphore:
                code, _ = await command('ping', '-n', '-I', interface, '-c', '1', '-W', '1', host, timeout=4, allowed=(0, 1))
                return host if code == 0 else None
        results = await asyncio.gather(*(ping(host) for host in sorted(hosts)), return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise RuntimeError(f'Ping sweep failed: {errors[0]}')
        _, raw = await command('ip', '-j', '-4', 'neigh', 'show', 'dev', interface)
        observations = parse_neighbours(json.loads(raw), networks, own_ips, set(results))
        if not self.settings.mdns:
            return observations
        # mDNS records enrich names only; they cannot refresh presence evidence.
        try:
            names = await discover_names({str(ip) for ip in own_ips}, {o.ip for o in observations})
            for observation in observations:
                observation.hostname = names.get(observation.ip)
        except Exception as exc:
            self.warnings.append(f'mDNS names unavailable: {exc}')
        return observations


class DemoDiscovery:
    networks = ['192.0.2.0/24 (demo)']
    warnings = []

    async def scan(self):
        return [Observation('02:00:00:00:00:01', '192.0.2.10', 'demo', True, 'demo-phone.local'),
                Observation('02:00:00:00:00:02', '192.0.2.20', 'demo', True, 'demo-printer.local')]
