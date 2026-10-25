import random
import string

from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

CHARSETS = {
    "letters": string.ascii_letters,
    "digits": string.digits,
    "special": "!@#$%^&*",
}


class Default:
    length = 12
    letters = True
    digits = True
    special = False


def gen_pass(length: int, letters: bool, digits: bool, special: bool) -> str:
    flags = (("letters", letters), ("digits", digits), ("special", special))
    chars = "".join(CHARSETS[name] for name, enabled in flags if enabled)
    return "".join(random.choices(chars or CHARSETS["letters"], k=length))
