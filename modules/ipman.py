import asyncio
import re
import time

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType
from loguru import logger

from . import config

logger.info(f"Загружен модуль {__name__}!")


def is_valid_ip(ip: str) -> bool:
    pattern = r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
    match = re.match(pattern, ip)
    if not match:
        return False
    return all(0 <= int(part) <= 255 for part in match.groups())


async def get_ip_info(ip: str) -> dict:
    """
    return: {
        "status": "success",
        "country": "Россия",
        "countryCode": "RU",
        "region": "KDA",
        "regionName": "Краснодарский край",
        "city": "Краснодар",
        "zip": "350000",
        "lat": 45.0355,
        "lon": 38.975,
        "timezone": "Europe/Moscow",
        "isp": "OJSC ****",
        "org": "OJSC ****",
        "as": "AS**** PJSC ***",
        "query": "*.***.***.***",
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip}",
                params={"lang": "ru"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                response.raise_for_status()
                return await response.json()
    except Exception:
        logger.trace("Ошибка при получении информации об IP")


async def check_proxy_ping(proxy_type: str, ipport: str) -> float | None:
    """
    Возвращает пинг в мс (float), если прокси жив.
    Возвращает None, если прокси мертв или ошибка.
    """
    url = "http://google.com"
    timeout = aiohttp.ClientTimeout(total=3)

    try:
        host, port = ipport.split(":")
        port = int(port)
        p_type = proxy_type.lower()

        start = time.perf_counter()

        if p_type == "http":
            proxy_url = f"http://{ipport}"
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, proxy=proxy_url) as resp:
                    if resp.status != 200:
                        return None
        else:
            p_map = {"socks5": ProxyType.SOCKS5, "socks4": ProxyType.SOCKS4}
            if p_type not in p_map:
                return None

            connector = ProxyConnector(proxy_type=p_map[p_type], host=host, port=port, rdns=True)
            try:
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return None
            finally:
                await connector.close()

        latency = (time.perf_counter() - start) * 1000
        return round(latency, 2)

    except Exception:
        return None


async def get_proxy_list() -> list[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                config.config.url.fp, timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                response.raise_for_status()
                return [
                    line.strip() for line in (await response.text()).splitlines() if line.strip()
                ]
    except Exception:
        logger.trace("Ошибка при получении списка прокси")
        return []


async def get_working_proxies(
    proxy_type: str = None, count: int = 5, max_concurrency: int = 5
) -> list[tuple[str, float]]:
    """Возвращает список кортежей ("ip:port", latency) отсортированный по latency.

    Проверки выполняются параллельно с ограничением `max_concurrency`.
    """
    proxies = await get_proxy_list()

    if proxy_type == "socks5":
        proxies = [p for p in proxies if p.lower().startswith("socks5")]
    elif proxy_type == "socks4":
        proxies = [p for p in proxies if p.lower().startswith("socks4")]
    elif proxy_type == "http":
        proxies = [p for p in proxies if p.lower().startswith("http")]

    sem = asyncio.Semaphore(max_concurrency)

    async def _check(proxy_line: str):
        try:
            ptype, ipport = proxy_line.split("://", 1)
        except Exception:
            return None

        async with sem:
            latency = await check_proxy_ping(ptype, ipport)

        if latency is None:
            return None
        return ipport, latency

    tasks = [asyncio.create_task(_check(p)) for p in proxies]
    results = await asyncio.gather(*tasks)

    working = [r for r in results if r is not None]
    working.sort(key=lambda x: x[1])

    return working[:count]
