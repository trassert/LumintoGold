import random
import string

CHARSETS = {
    "letters": string.ascii_letters,
    "digits": string.digits,
    "special": "!@#$%^&*",
}


class Default:
    length = 12
    letters = 0
    digits = 0
    special = 0


def gen_pass(length, letters, digits, special):
    parts = []
    if letters:
        parts.extend(random.choices(CHARSETS["letters"], k=letters))
    if digits:
        parts.extend(random.choices(CHARSETS["digits"], k=digits))
    if special:
        parts.extend(random.choices(CHARSETS["special"], k=special))

    used = len(parts)
    if used < length:
        all_chars = "".join(CHARSETS.values())
        parts.extend(random.choices(all_chars, k=length - used))
    elif used > length:
        parts = parts[:length]

    random.shuffle(parts)
    return "".join(parts)
