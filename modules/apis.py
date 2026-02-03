import aiohttp
from loguru import logger

from . import config, phrase

logger.info(f"Загружен модуль {__name__}!")


async def get_weather(city, token=""):
    if token == "":
        return phrase.weather.no_token
    async with aiohttp.ClientSession() as session:
        async with session.get(
            config.config.url.openweathermap.format(city=city, apikey=token),
            timeout=aiohttp.ClientTimeout(total=5),
        ) as response:
            data = await response.json()

    if data.get("cod") != 200:
        return phrase.weather.no_city

    return (
        f"🌡 : **Погода в {city.capitalize()}**\n"
        f"● Температура: {data['main']['temp']}°C\n"
        f"● Статус: {data['weather'][0]['description']}\n"
        f"● Влажность: {data['main']['humidity']}%\n"
        f"● Ветер: {data['wind']['speed']} м/с"
    )
