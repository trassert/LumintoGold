from datetime import datetime

import aiohttp
import pytz
from geopy.geocoders import Nominatim
from loguru import logger

from . import config

logger.info(f"Загружен модуль {__name__}!")

try:
    from timezonefinder import TimezoneFinder  # type: ignore

    tf = TimezoneFinder()

    async def get_timezone(lat, lon, api_key) -> str:
        return tf.timezone_at(
            lng=lon,
            lat=lat,
        )

    logger.info("Использую timezonefinder")
except ModuleNotFoundError:
    logger.warning("Использую geoapify, так как timezonefinder не установлен.")

    async def get_timezone(lat, lon, api_key) -> str | None:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                config.config.url.geoapify,
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "json",
                    "apiKey": api_key,
                },
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                return data["results"][0]["timezone"]["name"]


geolocator = Nominatim(user_agent="geo_assistant")


def time(timezone_name):
    try:
        return datetime.now(pytz.timezone(timezone_name)).strftime(
            "%H:%M:%S %d-%m-%Y"
        )
    except pytz.UnknownTimeZoneError:
        return "Неизвестный часовой пояс"
