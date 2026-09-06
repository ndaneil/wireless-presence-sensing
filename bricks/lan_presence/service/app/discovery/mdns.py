"""IPv4 DNS-SD name enrichment on the selected LAN addresses."""
import asyncio

# Also browse common types when a responder omits service-type enumeration.
COMMON_TYPES = {
    '_http._tcp.local.', '_https._tcp.local.', '_workstation._tcp.local.',
    '_ssh._tcp.local.', '_sftp-ssh._tcp.local.', '_ipp._tcp.local.',
    '_ipps._tcp.local.', '_printer._tcp.local.', '_airplay._tcp.local.',
    '_raop._tcp.local.', '_googlecast._tcp.local.', '_hap._tcp.local.',
    '_companion-link._tcp.local.', '_device-info._tcp.local.',
}


async def discover_names(interface_ips, known_ips, *, browse_seconds=4):
    """Returns IP -> .local hostname. Never infers presence from DNS records.

    Each scan uses a fresh cache and closes all browser, resolver and socket work.
    Service-type enumeration takes two seconds, followed by a four-second browse.
    Unknown IPs are ignored. ARP/neighbour discovery remains responsible for MACs.
    """
    if not interface_ips or not known_ips:
        return {}
    # Late import keeps the core/demo usable without optional network dependencies installed.
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf, AsyncZeroconfServiceTypes

    azc = AsyncZeroconf(interfaces=sorted(interface_ips), ip_version=IPVersion.V4Only)
    browser = None
    tasks = {}
    records = {}
    errors = []
    semaphore = asyncio.Semaphore(16)

    async def resolve(service_type, name):
        try:
            async with semaphore:
                info = AsyncServiceInfo(service_type, name)
                if not await info.async_request(azc.zeroconf, 1500):
                    return
                hostname = (info.server or '').rstrip('.').lower()
                if not hostname.endswith('.local') or len(hostname) > 253:
                    return
                records[(service_type, name)] = {
                    address: hostname for address in info.parsed_addresses(IPVersion.V4Only)
                    if address in known_ips
                }
        except Exception as exc:
            errors.append(exc)

    def changed(zeroconf, service_type, name, state_change):
        key = (service_type, name)
        if state_change is ServiceStateChange.Removed:
            records.pop(key, None)
            if key in tasks:
                tasks[key].cancel()
            return
        if key not in tasks and len(tasks) < 128:
            tasks[key] = asyncio.create_task(resolve(service_type, name))

    try:
        discovered = await AsyncZeroconfServiceTypes.async_find(aiozc=azc, timeout=2)
        types = sorted(COMMON_TYPES | set(discovered))[:64]
        browser = AsyncServiceBrowser(azc.zeroconf, types, handlers=[changed])
        await asyncio.sleep(browse_seconds)
    finally:
        try:
            if browser is not None:
                await browser.async_cancel()
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            await azc.async_close()
    if errors and not records:
        raise RuntimeError(f'mDNS service resolution failed: {errors[0]}')
    # Stable selection when a host advertises several services or aliases.
    names = {}
    for record in records.values():
        for address, hostname in record.items():
            names[address] = min(names.get(address, hostname), hostname)
    return names
