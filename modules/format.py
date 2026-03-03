import re

from loguru import logger

from . import phrase

logger.info(f"Загружен модуль {__name__}!")

_NAMES: dict[str, str] = {
    "rub": "RUB",
    "рубль": "RUB",
    "рубли": "RUB",
    "рублей": "RUB",
    "руб": "RUB",
    "usd": "USD",
    "доллар": "USD",
    "доллары": "USD",
    "долларов": "USD",
    "бакс": "USD",
    "баксов": "USD",
    "eur": "EUR",
    "евро": "EUR",
    "gbp": "GBP",
    "фунт": "GBP",
    "фунты": "GBP",
    "фунтов": "GBP",
    "jpy": "JPY",
    "йена": "JPY",
    "йены": "JPY",
    "йен": "JPY",
    "cny": "CNY",
    "юань": "CNY",
    "юани": "CNY",
    "юаней": "CNY",
    "chf": "CHF",
    "франк": "CHF",
    "франки": "CHF",
    "франков": "CHF",
    "kzt": "KZT",
    "тенге": "KZT",
    "uah": "UAH",
    "гривна": "UAH",
    "гривны": "UAH",
    "гривен": "UAH",
    "try": "TRY",
    "лира": "TRY",
    "лиры": "TRY",
    "лир": "TRY",
    "byn": "BYN",
    "белорусский рубль": "BYN",
    "aed": "AED",
    "дирхам": "AED",
    "дирхамы": "AED",
    "pln": "PLN",
    "злотый": "PLN",
    "злотые": "PLN",
    "злотых": "PLN",
    "czk": "CZK",
    "крона": "CZK",
    "кроны": "CZK",
    "крон": "CZK",
    "sek": "SEK",
    "шведская крона": "SEK",
    "nok": "NOK",
    "норвежская крона": "NOK",
    "dkk": "DKK",
    "датская крона": "DKK",
    "cad": "CAD",
    "канадский доллар": "CAD",
    "aud": "AUD",
    "австралийский доллар": "AUD",
    "hkd": "HKD",
    "гонконгский доллар": "HKD",
    "sgd": "SGD",
    "сингапурский доллар": "SGD",
    "inr": "INR",
    "рупия": "INR",
    "рупии": "INR",
    "рупий": "INR",
    "mxn": "MXN",
    "песо": "MXN",
    "brl": "BRL",
    "реал": "BRL",
    "реалы": "BRL",
    "реалов": "BRL",
}


def normalize_currency(value: str) -> str | None:
    return _NAMES.get(value.strip().lower(), value)


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
