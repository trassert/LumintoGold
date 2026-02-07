from pathlib import Path

import aiofiles
import orjson
from bestconfig import Config
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

config = Config(Path("configs") / "config.yml")
tokens = Config(Path("configs") / "tokens.yml")


async def load_client(clients_dir: Path, client_file: str):
    try:
        async with aiofiles.open(clients_dir / client_file, "rb") as f:
            data = orjson.loads(await f.read())
        phone = client_file.replace(".json", "")
        return phone, data["api_id"], data["api_hash"]
    except orjson.JSONDecodeError:
        logger.error(f"{client_file} пуст или неправильно размечен! Отключаем клиента..")
        return None
