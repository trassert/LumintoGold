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


async def conv_currency(currency: str, count: int = 1, default_type: str = "RUB") -> str:
    url = f"https://api.exchangerate.host/convert?from={currency.upper()}&to={default_type.upper()}&amount={count}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
    if not data.get("success"):
        return f"Не удалось конвертировать {currency.upper()} → {default_type.upper()}"
    result = data["result"]
    return phrase.currency.done.format(
        count1=count, cur1=currency.upper(), count2=result, cur2=default_type.upper()
    )
