from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

class Counter(dict):
    def __missing__(self, key):
        return 0


#! Deprecated - dont used in code
class StringIterator:
    def __init__(self, strings_list) -> None:
        self.strings_list = strings_list
        self.current_index = 0

    def last(self):
        return self.strings_list[self.current_index]

    def next(self):
        next_index = (self.current_index + 1) % len(self.strings_list)
        self.current_index = next_index
        return self.strings_list[next_index]
