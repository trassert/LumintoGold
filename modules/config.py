from pathlib import Path

import aiofiles
import orjson
import yaml
from loguru import logger
from sycm import ConfigManager, ConfigSection

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


config = ConfigManager(pathes.config, defaults=pathes.default_config)
tokens = ConfigManager(pathes.tokens, defaults=pathes.default_tokens)


def _load_section(path: Path, defaults: Path) -> ConfigSection:
    default_data = {}
    if defaults.exists():
        default_data = yaml.safe_load(
            defaults.read_text(encoding="utf-8")
        ) or {}
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(default_data, dict):
        raise ValueError(f"{path}: ожидается YAML-объект")
    return ConfigSection(data, default_data)


def reload() -> None:
    """Перечитывает config.yml и tokens.yml, сохраняя ссылки на объекты."""
    new_config = _load_section(pathes.config, pathes.default_config)
    new_tokens = _load_section(pathes.tokens, pathes.default_tokens)
    config._data = new_config
    tokens._data = new_tokens
    logger.info("Глобальные config.yml и tokens.yml перечитаны")


async def load_client(clients_dir: Path, client_file: str):
    try:
        async with aiofiles.open(clients_dir / client_file, "rb") as f:
            data = orjson.loads(await f.read())
        phone = client_file.replace(".json", "")
        return phone, data["api_id"], data["api_hash"]
    except orjson.JSONDecodeError:
        logger.error(
            f"{client_file} пуст или неправильно размечен! Отключаем клиента.."
        )
        return None
