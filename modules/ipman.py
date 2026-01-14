import httpx
import re

from loguru import logger

logger.info(f"Загружен модуль {__name__}!")


def is_valid_ip(ip: str) -> bool:
    pattern = r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
    match = re.match(pattern, ip)
    if not match:
        return False
    return all(0 <= int(part) <= 255 for part in match.groups())


def get_ip_info(ip: str) -> dict:
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
        response = httpx.get(
            f"http://ip-api.com/json/{ip}", params={"lang": "ru"}, timeout=5
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        logger.trace("Ошибка при получении информации об IP")
