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
    chars = ""

    if letters:
        chars += CHARSETS["letters"]
    if digits:
        chars += CHARSETS["digits"]
    if special:
        chars += CHARSETS["special"]

    if not chars:
        chars = CHARSETS["letters"]

    password = "".join(random.choices(chars, k=length))
    return password
