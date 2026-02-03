from pathlib import Path

from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

notes = Path("notes")
clients = Path("clients")
ai = Path("ai_chats")

tasks = Path("db") / "tasks.json"
animations = Path("animations") / "animations.json"
