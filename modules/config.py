from pathlib import Path
from bestconfig import Config
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

config = Config(Path("configs") / "config.yml")
tokens = Config(Path("configs") / "tokens.yml")
