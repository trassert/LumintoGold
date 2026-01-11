import pytz

from geopy.geocoders import Nominatim
from datetime import datetime

geolocator = Nominatim(user_agent="geo_assistant")


def get_timezone(lat, lon):
    return geolocator.reverse(
        f"{lat}, {lon}", addressdetails=True, language="en"
    ).raw.get("timezone")


def time(timezone_name):
    try:
        return datetime.now(pytz.timezone(timezone_name)).strftime(
            "%H:%M:%S %d-%m-%Y"
        )
    except pytz.UnknownTimeZoneError:
        return "Неизвестный часовой пояс"
