import random
import string

CHARSETS = {
    "letters": string.ascii_letters,
    "digits": string.digits,
    "special": "!@#$%^&*",
}


class Default:
    length = 12
    letters = 10
    digits = 2
    special = 0


def gen_pass(length:int, letters:int, digits:int, special:int) -> str:
    letters, digits, special = max(0, letters), max(0, digits), max(0, special)

    chars = (
        "".join(random.choices(CHARSETS["letters"], k=letters))
        + "".join(random.choices(CHARSETS["digits"], k=digits))
        + "".join(random.choices(CHARSETS["special"], k=special))
    )

    password = list(chars)
    random.shuffle(password)
    return "".join(password)[:length]
