import os
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

notes = "notes"

tasks = os.path.join("db", "tasks.json")
animations = os.path.join("animations", "animations.json")
