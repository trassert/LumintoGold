import re

from loguru import logger

from . import phrase

logger.info(f"Загружен модуль {__name__}!")

_ALIASES = {
    "RUB": "rub|рубль|рубли|рублей|руб",
    "USD": "usd|доллар|доллары|долларов|бакс|баксов",
    "EUR": "eur|евро",
    "GBP": "gbp|фунт|фунты|фунтов",
    "JPY": "jpy|йена|йены|йен",
    "CNY": "cny|юань|юани|юаней",
    "CHF": "chf|франк|франки|франков",
    "KZT": "kzt|тенге",
    "UAH": "uah|гривна|гривны|гривен",
    "TRY": "try|лира|лиры|лир",
    "BYN": "byn|белорусский рубль",
    "AED": "aed|дирхам|дирхамы",
    "PLN": "pln|злотый|злотые|злотых",
    "CZK": "czk|крона|кроны|крон",
    "SEK": "sek|шведская крона",
    "NOK": "nok|норвежская крона",
    "DKK": "dkk|датская крона",
    "CAD": "cad|канадский доллар",
    "AUD": "aud|австралийский доллар",
    "HKD": "hkd|гонконгский доллар",
    "SGD": "sgd|сингапурский доллар",
    "INR": "inr|рупия|рупии|рупий",
    "MXN": "mxn|песо",
    "BRL": "brl|реал|реалы|реалов",
}
_NAMES: dict[str, str] = {
    alias: code
    for code, names in _ALIASES.items()
    for alias in names.split("|")
}


def normalize_currency(value: str) -> str | None:
    return _NAMES.get(value.strip().lower(), value)


def f2vk(text: str) -> str:
    text = text or ""
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"\[.*?\]\(.*?\)", "", text)
    result = (phrase.from_tg + text.strip())[:4096]
    return result if result.strip() else phrase.from_tg.strip()


def splitter(text, chunk_size=4096):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def get_args(text: str, skip_first: bool = True) -> list[str]:
    parts = text.split()
    return parts[1:] if skip_first and parts else parts
