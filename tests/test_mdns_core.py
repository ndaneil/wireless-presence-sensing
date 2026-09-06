import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bricks/lan_presence/service'))
from app.discovery.mdns import discover_names
from app.discovery.linux import LinuxDiscovery
from app.config import Settings


class MdnsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.closed = False
        self.cancelled = False
        self.enumeration_error = None
        self.browser_started = asyncio.Event()
        self.entries = {'phone': ('Phone.local.', ['192.0.2.2', '10.0.0.2']),
                        'alias': ('Zebra.local.', ['192.0.2.2']),
                        'outside': ('Other.local.', ['10.0.0.3'])}
        owner = self
        class FakeZeroconf:
            def __init__(self, **kwargs):
                owner.options = kwargs
                self.zeroconf = self
            async def async_close(self):
                owner.closed = True
        class FakeTypes:
            @staticmethod
            async def async_find(**kwargs):
                if owner.enumeration_error:
                    raise owner.enumeration_error
                return ('_custom._tcp.local.',)
        class FakeInfo:
            def __init__(self, service_type, name):
                self.server, self.addresses = owner.entries[name]
            async def async_request(self, zc, timeout):
                owner.assertEqual(timeout, 1500)
                return True
            def parsed_addresses(self, version):
                return self.addresses
        class FakeBrowser:
            def __init__(self, zc, service_types, handlers):
                owner.assertIn('_custom._tcp.local.', service_types)
                owner.assertIn('_ipp._tcp.local.', service_types)
                owner.browser_started.set()
                for name in owner.entries:
                    handlers[0](zeroconf=zc, service_type='_http._tcp.local.', name=name,
                                state_change='Added')
            async def async_cancel(self):
                owner.cancelled = True
        base = types.ModuleType('zeroconf')
        base.IPVersion = types.SimpleNamespace(V4Only='v4')
        base.ServiceStateChange = types.SimpleNamespace(Removed='Removed')
        async_module = types.ModuleType('zeroconf.asyncio')
        async_module.AsyncZeroconf = FakeZeroconf
        async_module.AsyncZeroconfServiceTypes = FakeTypes
        async_module.AsyncServiceInfo = FakeInfo
        async_module.AsyncServiceBrowser = FakeBrowser
        self.modules = patch.dict(sys.modules, {'zeroconf': base, 'zeroconf.asyncio': async_module})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    async def test_daemon_free_resolution_on_selected_interface(self):
        names = await discover_names({'192.0.2.1'}, {'192.0.2.2'}, browse_seconds=0)
        self.assertEqual(names, {'192.0.2.2': 'phone.local'})
        self.assertEqual(self.options, {'interfaces': ['192.0.2.1'], 'ip_version': 'v4'})
        self.assertTrue(self.closed)
        self.assertTrue(self.cancelled)

    async def test_enumeration_failure_closes_sockets(self):
        self.enumeration_error = OSError('multicast unavailable')
        with self.assertRaises(OSError):
            await discover_names({'192.0.2.1'}, {'192.0.2.2'})
        self.assertTrue(self.closed)

    async def test_shutdown_cancels_browser_and_closes_sockets(self):
        task = asyncio.create_task(discover_names({'192.0.2.1'}, {'192.0.2.2'}, browse_seconds=100))
        await self.browser_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.closed)
        self.assertTrue(self.cancelled)

    async def test_no_advertisements_is_not_an_error(self):
        self.entries = {}
        self.assertEqual(await discover_names({'192.0.2.1'}, {'192.0.2.2'}, browse_seconds=0), {})
        self.assertTrue(self.closed)

    async def test_hostname_enrichment_does_not_confirm_stale_device(self):
        async def command(*args, **kwargs):
            if 'addr' in args:
                return 0, '[{"flags":["UP"],"addr_info":[{"local":"192.0.2.1","prefixlen":30,"scope":"global"}]}]'
            if args[0] == 'ping':
                return 1, ''
            if 'neigh' in args:
                return 0, '[{"dst":"192.0.2.2","lladdr":"02:00:00:00:00:01","state":["STALE"]}]'
            self.fail('Unexpected external command')
        with patch('app.discovery.linux.command', command), patch('app.discovery.linux.discover_names', return_value={'192.0.2.2': 'phone.local'}) as mdns:
            provider = LinuxDiscovery(Settings())
            result = await provider.scan()
        mdns.assert_awaited_once_with({'192.0.2.1'}, {'192.0.2.2'})
        self.assertEqual(result[0].hostname, 'phone.local')
        self.assertFalse(result[0].confirmed)
        self.assertEqual(provider.warnings, [])
