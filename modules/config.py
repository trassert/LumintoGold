from os import path

from bestconfig import Config
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

config = Config(path.join("configs", "config.yml"))
tokens = Config(path.join("configs", "tokens.yml"))
