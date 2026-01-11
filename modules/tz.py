import pytz

from geopy.geocoders import Nominatim
from datetime import datetime
from timezonefinder import TimezoneFinder

geolocator = Nominatim(user_agent="geo_assistant")
tf = TimezoneFinder()


def time(timezone_name):
    try:
        return datetime.now(pytz.timezone(timezone_name)).strftime(
            "%H:%M:%S %d-%m-%Y"
        )
    except pytz.UnknownTimeZoneError:
        return "Неизвестный часовой пояс"
