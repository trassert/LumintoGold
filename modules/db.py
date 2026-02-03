import aiofiles
import orjson
from loguru import logger

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


async def _load_json_async(filepath: str) -> dict:
    """Загружает JSON файл асинхронно. Возвращает {} при ошибке."""
    try:
        async with aiofiles.open(filepath, "rb") as f:
            raw = await f.read()
        return orjson.loads(raw) if raw else {}
    except (FileNotFoundError, orjson.JSONDecodeError, ValueError):
        logger.error(f"Ошибка при чтении файла {filepath}")
        return {}


async def get_animation(name) -> int:
    data = await _load_json_async(pathes.animations)
    return data.get(name, None)
