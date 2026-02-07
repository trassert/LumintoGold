from loguru import logger

logger.info(f"Загружен модуль {__name__}!")


class Counter(dict):
    def __missing__(self, key):
        return 0
