import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging():
    os.makedirs("logs", exist_ok=True)

    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
    )

    # Bot log
    bot_handler = RotatingFileHandler(
        "logs/bot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    bot_handler.setFormatter(logging.Formatter(log_format, date_format))
    bot_handler.setLevel(logging.INFO)

    # Error log
    error_handler = RotatingFileHandler(
        "logs/errors.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setFormatter(logging.Formatter(log_format, date_format))
    error_handler.setLevel(logging.ERROR)

    # Payments log
    payments_logger = logging.getLogger("payments")
    payments_handler = RotatingFileHandler(
        "logs/payments.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    payments_handler.setFormatter(logging.Formatter(log_format, date_format))
    payments_logger.addHandler(payments_handler)
    payments_logger.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.addHandler(bot_handler)
    root_logger.addHandler(error_handler)

    # Silence noisy libs
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    return logging.getLogger("bot")
