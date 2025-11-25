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


def gen_pass(length, letters, digits, special):
    letters, digits, special = max(0, letters), max(0, digits), max(0, special)
    total = letters + digits + special
    length = total if length == 0 or total > length else length

    chars = (
        "".join(random.choices(CHARSETS["letters"], k=letters))
        + "".join(random.choices(CHARSETS["digits"], k=digits))
        + "".join(random.choices(CHARSETS["special"], k=special))
    )

    remaining = length - len(chars)
    if remaining > 0:
        all_chars = (
            CHARSETS["letters"] + CHARSETS["digits"] + CHARSETS["special"]
        )
        chars += "".join(random.choices(all_chars, k=remaining))

    password = list(chars)
    random.shuffle(password)
    return "".join(password)
