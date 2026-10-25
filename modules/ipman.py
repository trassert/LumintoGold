import asyncio
import random
import re
import time

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType
from loguru import logger

from . import config

logger.info(f"Загружен модуль {__name__}!")

test_urls = [
    "http://google.com",
    "http://example.com",
    "http://github.com",
    "http://bing.com",
    "http://yahoo.com",
    "http://duckduckgo.com",
    "http://baidu.com",
    "http://yandex.ru",
]


def is_valid_ip(ip: str) -> bool:
    match = re.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", ip)
    return bool(match) and all(0 <= int(part) <= 255 for part in match.groups())


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
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                f"http://ip-api.com/json/{ip}",
                params={"lang": "ru"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response,
        ):
            response.raise_for_status()
            return await response.json()
    except Exception:
        logger.trace("Ошибка при получении информации об IP")


async def check_proxy_ping(proxy_type: str, ipport: str) -> float | None:
    """
    Возвращает пинг в мс (float), если прокси жив.
    Возвращает None, если прокси мертв или ошибка.
    """
    timeout = aiohttp.ClientTimeout(total=3)

    try:
        host, port = ipport.split(":")
        port = int(port)
        p_type = proxy_type.lower()

        start = time.perf_counter()

        if p_type == "http":
            proxy_url = f"http://{ipport}"
            async with aiohttp.ClientSession(timeout=timeout) as session:
                resp = await session.get(
                    random.choice(test_urls), proxy=proxy_url
                )
                if resp.status != 200:
                    return None
        else:
            p_map = {"socks5": ProxyType.SOCKS5, "socks4": ProxyType.SOCKS4}
            if p_type not in p_map:
                return None

            connector = ProxyConnector(
                proxy_type=p_map[p_type], host=host, port=port, rdns=True
            )
            try:
                async with (
                    aiohttp.ClientSession(
                        connector=connector, timeout=timeout
                    ) as session,
                    session.get(random.choice(test_urls)) as resp,
                ):
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
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                config.config.url.fp,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response,
        ):
            response.raise_for_status()
            return [
                line.strip()
                for line in (await response.text()).splitlines()
                if line.strip()
            ]
    except Exception:
        logger.trace("Ошибка при получении списка прокси")
        return []


async def get_working_proxies(
    proxy_type: str | None = None,
    count: int = 5,
    max_concurrency: int = 100,
) -> list[tuple[str, str, float]]:
    """Возвращает список кортежей ("proxy_type", "ip:port", latency) отсортированный по latency.

    Проверки выполняются параллельно с ограничением `max_concurrency`.
    """
    proxies = await get_proxy_list()
    if proxy_type in ("socks5", "socks4", "http"):
        proxies = [p for p in proxies if p.lower().startswith(proxy_type)]

    sem = asyncio.Semaphore(max_concurrency)

    async def _check(proxy_line: str):
        try:
            ptype, ipport = proxy_line.split("://", 1)
        except ValueError:
            return None
        async with sem:
            latency = await check_proxy_ping(ptype, ipport)
        return (ptype, ipport, latency) if latency is not None else None

    results = await asyncio.gather(*(_check(proxy) for proxy in proxies))
    working = sorted((r for r in results if r is not None), key=lambda x: x[2])
    return working[:count]
