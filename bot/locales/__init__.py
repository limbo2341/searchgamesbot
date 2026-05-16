from bot.locales.en.texts import texts as en_texts
from bot.locales.ru.texts import texts as ru_texts
from bot.locales.ua.texts import texts as ua_texts

LOCALES = {
    "en": en_texts,
    "ru": ru_texts,
    "ua": ua_texts,
}


def get_text(key: str, language: str = "en", **kwargs) -> str:
    locale = LOCALES.get(language, en_texts)
    text = locale.get(key, en_texts.get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def t(key: str, language: str = "en", **kwargs) -> str:
    return get_text(key, language, **kwargs)


__all__ = ["get_text", "t", "LOCALES"]
