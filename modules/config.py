from pathlib import Path

import aiofiles
import orjson
import yaml
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")


class ConfigSection(dict):
    "Конфиг-секции для менеджера. Dict -> ConfigSection."

    def __init__(self, data):
        super().__init__(data)
        for key, value in data.items():
            if isinstance(value, dict):
                self[key] = ConfigSection(value)
            elif isinstance(value, list):
                self[key] = [ConfigSection(i) if isinstance(i, dict) else i for i in value]

    def __getattr__(self, key):
        return self.get(key)


class ConfigManager:
    "Root. Вызывается."

    def __init__(self, path: Path):
        logger.info(f"Зарегестрирован конфиг {path}")
        raw_data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._data = ConfigSection(raw_data)

    def __getattr__(self, key):
        return getattr(self._data, key)


config = ConfigManager(Path("configs") / "config.yml")
tokens = ConfigManager(Path("configs") / "tokens.yml")


async def load_client(clients_dir: Path, client_file: str):
    try:
        async with aiofiles.open(clients_dir / client_file, "rb") as f:
            data = orjson.loads(await f.read())
        phone = client_file.replace(".json", "")
        return phone, data["api_id"], data["api_hash"]
    except orjson.JSONDecodeError:
        logger.error(f"{client_file} пуст или неправильно размечен! Отключаем клиента..")
        return None
