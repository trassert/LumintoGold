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


async def conv_currency(currency: str, count: int = 1, default_type: str = "RUB", token: str = "") -> str:
    currency = currency.upper()
    default_type = default_type.upper()

    async with aiohttp.ClientSession() as session:
        async with session.get(config.config.url.exchangerate.format(token=token, currency=currency)) as resp:
            data: dict = await resp.json()

    if data.get("result", None) != "success":
        return phrase.currency.error
    if default_type not in data["rates"]:
        return phrase.currency.no_currency.format(default_type)

    result = round(data["rates"][default_type] * count, 2)
    return phrase.currency.done.format(count1=count, cur1=currency, count2=result, cur2=default_type)
