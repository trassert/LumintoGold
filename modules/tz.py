import pytz
import requests

from loguru import logger
from geopy.geocoders import Nominatim
from datetime import datetime

from . import config


logger.info(f"Загружен модуль {__name__}!")

try:
    from timezonefinder import TimezoneFinder  # type: ignore

    tf = TimezoneFinder()

    def get_timezone(lat, lon, api_key) -> str:
        return tf.timezone_at(
            lon,
            lat,
        )

    logger.info("Использую timezonefinder")
except ModuleNotFoundError:
    logger.warning("Использую geoapify, так как timezonefinder не установлен.")
    def get_timezone(lat, lon, api_key) -> str | None:
        r = requests.get(
            config.config.geoapify_url,
            params={"lat": lat, "lon": lon, "format": "json", "apiKey": api_key},
            timeout=5,
        )
        if not r.status_code == 200:
            return None
        return r.json()['results'][0]['timezone']['name']

geolocator = Nominatim(user_agent="geo_assistant")


def time(timezone_name):
    try:
        return datetime.now(pytz.timezone(timezone_name)).strftime(
            "%H:%M:%S %d-%m-%Y"
        )
    except pytz.UnknownTimeZoneError:
        return "Неизвестный часовой пояс"
