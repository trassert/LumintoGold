import re

from loguru import logger

from . import phrase

logger.info(f"Загружен модуль {__name__}!")


def f2vk(text: str) -> str:
    if not text:
        text = ""
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"\[.*?\]\(.*?\)", "", text)
    result = (phrase.from_tg + text.strip())[:4096]
    return result if result.strip() else phrase.from_tg.strip()


def splitter(text, chunk_size=4096):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def get_args(text: str, skip_first: bool = True) -> list[str]:
    parts = text.split()
    return parts[1:] if skip_first and parts else parts
